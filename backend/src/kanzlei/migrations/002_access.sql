-- Who may see what, decided by Postgres for every query (docs/adr/0001).
--   buchhaltung: the clients assigned to them
--   berater:     every client of their firm
--   gruppe:      the group's engineers: no client data at all, only per-firm aggregates and
--                account mappings (need-to-know, § 203 StGB / § 62a StBerG)
--   system:      the worker and imports (app.system = on)
-- The client portal reaches its own questions only through the SECURITY DEFINER functions below.

CREATE FUNCTION app_login() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.login', true), '') $$;

CREATE FUNCTION app_system() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.system', true), '') = 'on' $$;

CREATE FUNCTION app_firm() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT firm_id FROM staff WHERE login = app_login() $$;

CREATE FUNCTION app_role() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT role FROM staff WHERE login = app_login() $$;

CREATE FUNCTION app_client_visible(cid text) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT app_system() OR EXISTS (
    SELECT 1 FROM clients c JOIN staff s ON s.login = app_login() AND s.firm_id = c.firm_id
    WHERE c.id = cid AND (s.role = 'berater' OR EXISTS (SELECT 1 FROM assignments a WHERE a.login = s.login AND a.client_id = c.id))
  )
$$;

ALTER TABLE firms ENABLE ROW LEVEL SECURITY;           ALTER TABLE firms FORCE ROW LEVEL SECURITY;
ALTER TABLE staff ENABLE ROW LEVEL SECURITY;           ALTER TABLE staff FORCE ROW LEVEL SECURITY;
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;         ALTER TABLE clients FORCE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;     ALTER TABLE assignments FORCE ROW LEVEL SECURITY;
ALTER TABLE firm_accounts ENABLE ROW LEVEL SECURITY;   ALTER TABLE firm_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE counterparties ENABLE ROW LEVEL SECURITY;  ALTER TABLE counterparties FORCE ROW LEVEL SECURITY;
ALTER TABLE statements ENABLE ROW LEVEL SECURITY;      ALTER TABLE statements FORCE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;    ALTER TABLE transactions FORCE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;       ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE closes ENABLE ROW LEVEL SECURITY;          ALTER TABLE closes FORCE ROW LEVEL SECURITY;
ALTER TABLE items ENABLE ROW LEVEL SECURITY;           ALTER TABLE items FORCE ROW LEVEL SECURITY;
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;        ALTER TABLE bookings FORCE ROW LEVEL SECURITY;
ALTER TABLE queries ENABLE ROW LEVEL SECURITY;         ALTER TABLE queries FORCE ROW LEVEL SECURITY;
ALTER TABLE query_items ENABLE ROW LEVEL SECURITY;     ALTER TABLE query_items FORCE ROW LEVEL SECURITY;
ALTER TABLE corrections ENABLE ROW LEVEL SECURITY;     ALTER TABLE corrections FORCE ROW LEVEL SECURITY;
ALTER TABLE imports ENABLE ROW LEVEL SECURITY;         ALTER TABLE imports FORCE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;          ALTER TABLE events FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;            ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;          ALTER TABLE outbox FORCE ROW LEVEL SECURITY;

CREATE POLICY firms_read ON firms FOR SELECT USING (app_system() OR id = app_firm() OR app_role() = 'gruppe');
CREATE POLICY firms_write ON firms FOR ALL USING (app_system()) WITH CHECK (app_system());

CREATE POLICY staff_read ON staff FOR SELECT USING (app_system() OR login = app_login() OR firm_id = app_firm() OR app_role() = 'gruppe');
CREATE POLICY staff_write ON staff FOR ALL USING (app_system()) WITH CHECK (app_system());

CREATE POLICY clients_read ON clients FOR SELECT USING (app_client_visible(id));
CREATE POLICY clients_write ON clients FOR ALL USING (app_system()) WITH CHECK (app_system());

CREATE POLICY assignments_read ON assignments FOR SELECT USING (app_system() OR login = app_login() OR app_client_visible(client_id) AND app_role() = 'berater');
CREATE POLICY assignments_write ON assignments FOR ALL USING (app_system()) WITH CHECK (app_system());

CREATE POLICY firm_accounts_read ON firm_accounts FOR SELECT USING (app_system() OR firm_id = app_firm() OR app_role() = 'gruppe');
CREATE POLICY firm_accounts_map ON firm_accounts FOR UPDATE
  USING (app_system() OR app_role() = 'gruppe' OR (firm_id = app_firm() AND app_role() = 'berater'))
  WITH CHECK (app_system() OR app_role() = 'gruppe' OR (firm_id = app_firm() AND app_role() = 'berater'));
CREATE POLICY firm_accounts_insert ON firm_accounts FOR INSERT WITH CHECK (app_system());

-- Client data: one rule for all of it.
CREATE POLICY counterparties_all ON counterparties FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY statements_all ON statements FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY transactions_all ON transactions FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY documents_all ON documents FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY closes_all ON closes FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY items_all ON items FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY bookings_all ON bookings FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY queries_all ON queries FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY query_items_all ON query_items FOR ALL USING (app_client_visible(client_id)) WITH CHECK (app_client_visible(client_id));
CREATE POLICY imports_all ON imports FOR ALL USING (app_system() OR (client_id IS NOT NULL AND app_client_visible(client_id))) WITH CHECK (app_system());
CREATE POLICY outbox_system ON outbox FOR ALL USING (app_system() OR app_client_visible(client_id)) WITH CHECK (app_system() OR app_client_visible(client_id));
CREATE POLICY jobs_system ON jobs FOR ALL USING (app_system() OR created_by = app_login()) WITH CHECK (app_system() OR created_by = app_login());

-- Corrections: written by whoever corrects; read by the firm and the group (they carry families,
-- tax codes and pseudonymous ids, no names or amounts).
CREATE POLICY corrections_write ON corrections FOR INSERT WITH CHECK (app_client_visible(client_id));
CREATE POLICY corrections_read ON corrections FOR SELECT USING (app_system() OR firm_id = app_firm() OR app_role() = 'gruppe');

CREATE POLICY events_read ON events FOR SELECT USING (app_system() OR (firm_id = app_firm() AND app_role() = 'berater'));
CREATE POLICY events_insert ON events FOR INSERT WITH CHECK (false);  -- only through append_event()

-- The protocol: one chain, serialized by an advisory lock.
CREATE FUNCTION append_event(p_actor text, p_firm text, p_client text, p_kind text, p_payload jsonb)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE prev text; h text; new_id bigint; ts timestamptz := clock_timestamp();
BEGIN
  PERFORM pg_advisory_xact_lock(880011);
  SELECT hash INTO prev FROM events ORDER BY id DESC LIMIT 1;
  prev := coalesce(prev, repeat('0', 64));
  h := encode(sha256(convert_to(prev || '|' || p_actor || '|' || coalesce(p_firm, '') || '|' || coalesce(p_client, '') || '|' ||
        p_kind || '|' || p_payload::text || '|' || to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'), 'UTF8')), 'hex');
  INSERT INTO events (at, actor, firm_id, client_id, kind, payload, prev_hash, hash)
  VALUES (ts, p_actor, p_firm, p_client, p_kind, p_payload, prev, h) RETURNING id INTO new_id;
  RETURN new_id;
END $$;

-- Client portal: a token reaches exactly one question bundle, nothing else.
CREATE FUNCTION portal_bundle(p_token_hash text)
RETURNS TABLE (query_id bigint, client_name text, firm_name text, period text, due_on date, status text,
               item_id bigint, reason text, question text, options jsonb, answer jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT q.id, c.name, f.name, q.period, q.due_on, q.status, qi.item_id, qi.reason, qi.question, qi.options, qi.answer
  FROM queries q JOIN clients c ON c.id = q.client_id JOIN firms f ON f.id = c.firm_id
  JOIN query_items qi ON qi.query_id = q.id
  WHERE q.token_hash = p_token_hash AND q.status <> 'geschlossen'
  ORDER BY qi.id
$$;

CREATE FUNCTION portal_answer(p_token_hash text, p_item bigint, p_answer jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE qid bigint; cid text; n int;
BEGIN
  SELECT q.id, q.client_id INTO qid, cid FROM queries q WHERE q.token_hash = p_token_hash AND q.status = 'offen';
  IF qid IS NULL THEN RETURN false; END IF;
  UPDATE query_items SET answer = p_answer, answered_at = now() WHERE query_id = qid AND item_id = p_item;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n = 0 THEN RETURN false; END IF;
  IF NOT EXISTS (SELECT 1 FROM query_items WHERE query_id = qid AND answer IS NULL) THEN
    UPDATE queries SET status = 'beantwortet', answered_at = now() WHERE id = qid;
  END IF;
  PERFORM append_event('portal', (SELECT firm_id FROM clients WHERE id = cid), cid, 'portal.answer',
                       jsonb_build_object('item', p_item, 'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_answer) k)));
  RETURN true;
END $$;

-- Per-firm aggregates for the group's engineers and each firm's tax advisors.
CREATE FUNCTION rollout(p_period text)
RETURNS TABLE (firm_id text, firm_name text, chart text, clients bigint, items bigint, auto bigint, accepted bigint,
               corrected bigint, by_client bigint, open_review bigint, open_client bigint, parked bigint,
               signed_off bigint, unmapped_accounts bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT f.id, f.name, f.chart,
    (SELECT count(*) FROM clients c WHERE c.firm_id = f.id),
    count(i.id),
    count(i.id) FILTER (WHERE i.decision = 'auto'),
    count(i.id) FILTER (WHERE i.decision = 'accepted'),
    count(i.id) FILTER (WHERE i.decision = 'corrected'),
    count(i.id) FILTER (WHERE i.decision = 'client'),
    count(i.id) FILTER (WHERE i.state = 'review'),
    count(i.id) FILTER (WHERE i.state = 'client'),
    count(i.id) FILTER (WHERE i.state = 'parked'),
    (SELECT count(*) FROM closes cl JOIN clients c ON c.id = cl.client_id WHERE c.firm_id = f.id AND cl.period = p_period AND cl.status = 'festgeschrieben'),
    (SELECT count(*) FROM firm_accounts fa WHERE fa.firm_id = f.id AND fa.family IS NULL)
  FROM firms f
  LEFT JOIN clients c ON c.firm_id = f.id
  LEFT JOIN items i ON i.client_id = c.id AND i.period = p_period
  WHERE app_system() OR app_role() = 'gruppe' OR (app_role() = 'berater' AND f.id = app_firm())
  GROUP BY f.id, f.name, f.chart
  ORDER BY f.name
$$;

-- The application's role: subject to every policy above.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kanzlei_app') THEN
    CREATE ROLE kanzlei_app LOGIN NOBYPASSRLS;
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO kanzlei_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO kanzlei_app;
REVOKE UPDATE ON events FROM kanzlei_app;
REVOKE INSERT ON events FROM kanzlei_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO kanzlei_app;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO kanzlei_app;
