// Responses recorded from the seeded demo API (simulated firms; no real data).
import type {
  BoardRow,
  DemoUser,
  Family,
  ItemDetailResponse,
  ItemsResponse,
  PortalBundle,
  QueryBundle,
  Rollout,
  User,
  Ustva,
} from "../src/shared/api/types";
import boardJson from "./fixtures/board.json";
import demoUsersJson from "./fixtures/demo_users.json";
import evaluationJson from "./fixtures/evaluation.json";
import familiesJson from "./fixtures/families.json";
import itemAutoJson from "./fixtures/item_auto.json";
import itemClientJson from "./fixtures/item_client.json";
import itemReviewJson from "./fixtures/item_review.json";
import itemsJson from "./fixtures/items.json";
import meJson from "./fixtures/me.json";
import meBuchhaltungJson from "./fixtures/me_buchhaltung.json";
import meGroupJson from "./fixtures/me_group.json";
import periodsJson from "./fixtures/periods.json";
import portalJson from "./fixtures/portal.json";
import queriesJson from "./fixtures/queries.json";
import rolloutJson from "./fixtures/rollout.json";
import rolloutPeriodsJson from "./fixtures/rollout_periods.json";
import ustvaOpenJson from "./fixtures/ustva_open.json";
import ustvaSignedJson from "./fixtures/ustva_signed.json";

export const berater = meJson as User;
export const buchhaltung = meBuchhaltungJson as User;
export const gruppe = meGroupJson as User;
export const demoUsers = demoUsersJson as DemoUser[];
export const periods = periodsJson as string[];
export const board = boardJson as BoardRow[];
export const items = itemsJson as ItemsResponse;
export const itemClient = itemClientJson as ItemDetailResponse;
export const itemReview = itemReviewJson as ItemDetailResponse;
export const itemAuto = itemAutoJson as ItemDetailResponse;
export const families = familiesJson as Family[];
export const queries = queriesJson as QueryBundle[];
export const ustvaOpen = ustvaOpenJson as Ustva;
export const ustvaSigned = ustvaSignedJson as Ustva;
export const rolloutPeriods = rolloutPeriodsJson as string[];
export const rollout = rolloutJson as Rollout;
export const portal = portalJson as PortalBundle;
export const evaluation = evaluationJson;

export const CLIENT = "hp-10101";
export const PERIOD = "2026-09";
export const C = `/api/clients/${CLIENT}/periods`;
