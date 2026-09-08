# Ready-to-use wording for each bundle-match outcome

Written by `chessathon-64` at the request of `chessathon-bb`, **before any result exists** — the
match is still running as this is written. That is deliberate and it is the same discipline as the
pre-registration in `DECISIONS.md` (`954122e`): wording drafted after seeing the number gets tuned
to flatter it, and case 3 in particular is the sentence a judge will read hardest.

Placeholders in `<angle brackets>` are filled from the arena row. Nothing else should change.

---

## Case 1 — interval above zero: promoted on the Elo rule

**`docs/RESULTS.md`, prose under the row:**

> ### 2026-09-08 — v1.1 promoted: the timing refit and the king-danger term
>
> `v1.1-bundle-vs-v1.0-real` returns **<score> (<interval>), Elo <elo>**, over 300 games at the real
> time control against `versions/v1.0`. The lower bound is above zero, so this is CLAUDE.md's
> promotion rule met on its own terms and v1.1 replaces v1.0.
>
> The match measures **two changes together** — the timing refit (`82b20e2`) and the king-danger
> term (`897e1e2`). That is the right question for the upload decision and the wrong one for the
> record: this result says the pair is an improvement and cannot say which half earned it, or
> whether one half is negative and carried by the other. A timing-alone match against
> `versions/v1.0` follows for attribution; until it lands, neither change has an individual number.

**`docs/report.tex`:** update the abstract to name v1.1 as the shipped build with this interval;
add a v1.1 addendum in the shape of the v1.0 one; in *Known limitations*, change the king-danger
`\emph{Status.}` paragraph to say the term ships and was measured **only as part of a bundle**; and
in *What is next*, replace the "neither has won a promotion match" paragraph with the result and the
outstanding attribution match.

---

## Case 2 — reverted: the changes lost

**`docs/RESULTS.md`, prose under the row:**

> ### 2026-09-08 — v1.1 rejected: the bundle did not beat v1.0
>
> `v1.1-bundle-vs-v1.0-real` returns **<score> (<interval>), Elo <elo>**, over 300 games at the real
> time control. <Under the rule pre-registered before the match was run (DECISIONS.md, 2026-09-08),
> this reverts: the point estimate is negative / the lower bound is at or below −40 Elo.> Both
> changes are reverted on `main` and **v1.0 remains the shipped build**.
>
> Kept here in full, like the Texel rows above. Two changes that were carefully argued from platform
> evidence — a divisor refit measured against 1 697 ladder games, and an evaluation term with a lost
> game behind it — did not survive a 300-game match. That is what the promotion rule is for, and the
> rule binding a change we believed in is the only evidence that it binds at all.

**`docs/report.tex`:** the report needs **no** structural change — it already describes v1.0. Add
this outcome to *What is next*, replacing the "neither has won a promotion match" paragraph, and
keep the king-danger limitation as a live gap rather than a fixed one. This case makes the report
stronger, not weaker: a negative result on the team's own preferred change is the clearest possible
demonstration of the method.

---

## Case 3 — straddles zero, promoted on the safety criterion

This is the one to get right. It must be legible as a *deviation*, taken deliberately, on a rule
fixed in advance — not as a rule bent around a disappointing number.

**`docs/RESULTS.md`, prose under the row:**

> ### 2026-09-08 — v1.1 promoted on the safety criterion, not on Elo
>
> `v1.1-bundle-vs-v1.0-real` returns **<score> (<interval>), Elo <elo>**, over 300 games at the real
> time control against `versions/v1.0`. **The interval includes zero, so the strength claim is not
> proven and none is made.** The lowest clock any game reached rose from **<v1.0 low_clock> to
> <v1.1 low_clock> ms**, with no loss on time in either direction.
>
> It is promoted under case 3 of the rule pre-registered *before the match was run*
> (`DECISIONS.md`, 2026-09-08, commit `954122e`), which permits promotion on a measured reduction in
> flag risk when the Elo interval straddles zero, the point estimate is non-negative and the lower
> bound is above −40.
>
> **Why the instrument, not the change, is what failed here.** The timing refit exists because two of
> our seven rated games finished on 4.7 s and 6.0 s of a 120 s clock, and a flag loses a game
> outright. That effect lives in the minority of games long enough for the divisor to bite, so a
> 300-game match dilutes it across a majority of games where the change does nothing. "Not proven"
> from a badly matched instrument is not evidence of absence.
>
> **What this does not claim.** The king-danger term (`897e1e2`) has no independent safety argument
> and rides along in this bundle. **It ships unproven**, and no strength claim is made for it either.
> A timing-alone match against `versions/v1.0` follows for the record.

**`docs/report.tex`:** the abstract must say v1.1 ships and that **no strength improvement over
v1.0 is claimed** — do not let the +Elo point estimate appear anywhere without its interval beside
it. The v1.1 addendum states the promotion criterion used, in the first sentence, and quotes the
pre-registration date. *Known limitations* gains an entry: "the shipped build carries an evaluation
term that has never won a match of its own."

---

## The sentence to avoid, in every case

Do not write that the change "did not have time to be measured properly", or that a larger match
"would have" cleared the bar. Neither is known. What is known is the interval that was returned and
the criterion that was fixed beforehand; both go in the record, and the reader draws their own
conclusion.
