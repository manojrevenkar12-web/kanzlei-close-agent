# 9. Frontend

Status: accepted

- React 19, Vite, TanStack Query, framer-motion, CSS modules over one token file
  (`web/src/shared/theme/tokens.css` and `tokens.ts`): no colours, sizes or durations in components.
- Feature-first folders: `features/{auth,board,client,group,quality,portal}`, shared `api`, `lib`,
  `theme`, `ui`.
- Every query goes through `QueryState`: skeleton while loading, error with retry, an empty state that
  says what to do next.
- The visual language is the accountant's: Soll and Haben columns with the red Haben rule, amounts in
  red ink when money goes out, a runway bar per client for the month, a sign-off stamp. Motion is used
  where something changed: the stamp landing, the correction form opening, the detail sliding in.
  `MotionConfig reducedMotion="user"` respects the system setting.
- Keyboard: `j`/`k` move through items, `a` accepts a proposal under review.
- Tests: Vitest flows on recorded API responses (`web/test`), Playwright on the seeded demo for desktop
  and a phone (`web/e2e`), including a check that no screen scrolls sideways on a phone.
