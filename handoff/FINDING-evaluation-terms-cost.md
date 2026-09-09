# What cheap evaluation knowledge we could add, and what each would actually cost us

Research only, no box. The question was: what evaluation terms exist that we lack, what is each
worth, and what does each cost *in our engine*. The answer is dominated by the cost column, and the
cost column has three structural facts in it that make most published advice inapplicable to us.

## 1. The "mobility is free if you reuse the generator" lead does not transfer. Three reasons.

This is the lead worth killing first, because two sessions are chasing it and MadChess is reported
to get mobility "essentially for free" by counting attack sets its generator already builds.

**(a) Our generator does not build attack sets.** `fastboard.gen_pseudo` walks the piece lists and
writes *packed moves* into an `int32` buffer. There is no set to count. `fastboard.attacked` is a
boolean "is this square attacked", and it scans *outward from the square* rather than over the
attackers — it cannot be accumulated into per-piece counts without being rewritten into a different
algorithm. The free-mobility trick is a **bitboard** property: those engines compute an attack
bitboard per piece anyway and mobility is a `popcount` of it. The Chessprogramming wiki is explicit
that this is how bitboard engines get it, and that 0x88 engines determine slider attacks by walking
rays. We are a 0x88 mailbox. There is nothing lying around to count.

**(b) The evaluation runs *before* move generation, by design.** This is the decisive one. In
`fastsearch.quiescence` the stand-pat `_cached_eval` is called at the top and `gen_captures` only
afterwards. In `fastsearch.negamax`, reverse futility, the null-move test and futility pruning all
read `_cached_eval` *before* any move generation. That ordering is the entire point of those cuts:
they exist so that move generation can be **skipped**. Any evaluation term that needs the move list
would force generation before the decision to prune, destroying exactly the saving the pruning
exists to produce. The dependency runs the wrong way.

**(c) The evaluation is memoised.** `_cached_eval` keys on the position, so an evaluation that
depended on search-local state (a move buffer at a given ply) could not be cached and would be
recomputed at every visit.

**Conclusion: for us, a term that needs to know what pieces attack costs a ray walk, full stop.**
Price it accordingly and do not budget for a discount that our board representation cannot give.

## 2. What that means for pricing, with our one real measurement

The only term we have actually measured end-to-end is mobility: **9 % of the node rate at depth 7
and 11 % at depth 8** (`tools/bench_mobility.py`, paired, 120 pairs, median 0.9109 against pooled
0.9127). That is about 0.11 of a ply — roughly 5–9 Elo of pure speed cost.

**A correction that changes a live decision.** Mobility is currently described as costing "1.7×
time-to-depth, therefore a net loss". That figure appears to compose the measured node-rate cost
(~1.10) with a *nodes-to-depth* ratio of ~1.58. `docs/DECISIONS.md` on the mobility branch records
that the nodes-to-depth ratio **is not quotable**: it came out 2.19, 1.13, 1.58 and 0.96 across runs
differing only in which positions were sampled. It is not resolvable from that data.

The distinction that matters, and it is the one that came out of pricing the ordering bundle: an
**ordering** change genuinely shrinks the tree, so its nodes-to-depth ratio is a real systematic
effect and must be composed with the rate. A pure **evaluation** term has no such mechanism, so
node rate is the whole story and the sampled tree ratio is noise. Applying the ordering framing to
an evaluation term produces a cost roughly seven times too large. Mobility's honest price is 9–11 %
of node rate, not 70 % of time-to-depth.

**Ray-walking terms are cheaper together than separately.** The Chessprogramming wiki notes that
king-zone attack knowledge "is likely to be uncovered while calculating mobility" — the attack-unit
count and the mobility count are two accumulations over the *same* ray walk. So mobility plus
attacker-count king safety costs close to one ray walk, not two. If either is tried, they should be
tried together; costing them independently overstates the pair by nearly a factor of two.

## 3. The published-Elo column is weak evidence for us, and here is the concrete reason

Per-term Elo figures with error bars and game counts are scarce — most engine development records
a pass/fail SPRT rather than a point estimate, and the figures that circulate come from engines far
stronger than ours, where the baseline evaluation is far better and a marginal term is fighting for
a much smaller share.

**This is the lens that was discarded on 8 September** after a search-technique batch chosen by
published Elo measured −21 in our engine. Nothing has changed that makes it safer for evaluation
terms than it was for search techniques.

Concrete counter-evidence, and it is directly on the term we would most want. A TalkChess thread
titled "Underwhelming results from king safety evaluation" reports an engine author adding a
king-safety term and measuring **−10 Elo**, improving to **−8 Elo** after fixing a bug, and about a
**−100 Elo** regression when tuned against a different dataset. The author's diagnosis is that the
tuned bonus came out at **+7 centipawns for a large attack** where pre-NNUE Stockfish used about
**+500**, because the training positions contained too few heavy attacks to constrain the parameter.

That diagnosis should be read carefully here, because it is the same failure that killed our
network today: **a term fitted on positions where it rarely applies gets a coefficient near zero and
then does nothing.** Our own king-danger constants are a hand-chosen prior rather than a fit
(`docs/PROVENANCE.md`), which sidesteps that particular trap.

## 4. Per-term assessment

Ordered by what I would actually try, not by published value.

| term | what it needs | our cost | evidence |
| --- | --- | --- | --- |
| **King danger, attacker-count table** | ray walk from the king zone | shares mobility's walk; near-free *if* mobility is also added, ~9–11 % alone | design is standard (attack units 2/2/3/5 into a nonlinear table). Direct measured evidence is one author's −8 to −10 Elo. We already have a capped-quadratic version behind `KING_DANGER_TERM`; what we lack is the *table*, not the idea |
| **Threats: attacked-and-undefended** | attacker *and* defender query per piece — two `attacked` scans per piece, or a ray walk | expensive for us: `attacked` scans outward per square, so this is ~2× a mobility walk | targets a real defect (our blunder rate 1.8 % against the field's 0.0–0.9 %). No measured figure found |
| **Rook on 7th, connected rooks** | piece list and file/rank arithmetic only | **genuinely cheap** — one pass over the rook entries, no ray walk, folds into the existing first pass in `fasteval.evaluate` | no measured figure found; textbook magnitude |
| **Passed-pawn king distance** | pawn summary (already computed) plus king squares (already in `meta`) | **genuinely cheap** — the data is already in hand, it is arithmetic on `S_TOP`/`S_BOTTOM` and `M_KING` | no measured figure found; the mechanism is uncontroversial in endgames |
| **Outposts** | pawn-attack test on one square per knight/bishop | cheap: the pawn summary already knows which files hold enemy pawns | no measured figure found |
| **Space** | count of safe squares behind the pawn front | needs enemy pawn attack spans — derivable from the per-file summary | moderate; no measured figure found |
| **Mobility (plain)** | ray walk per piece | **measured: 9–11 % of node rate** | implemented on `ct-mobility`, gated, never screened |

## 5. Negative results — things not to try at our node budget

* **Anything that needs per-piece attack *sets*.** Not because it is worthless but because our board
  representation cannot produce them cheaply, and the search calls the evaluation before it
  generates moves. This kills the whole "reuse the generator" family for us specifically.
* **A deep NNUE-style output head.** Measured, not argued: 915–1 436 ns per evaluation against a
  1 270 ns node (`tools/bench_accumulator.py`). A quarter to a third of the node rate.
* **King safety re-tuned on our existing position sets.** The TalkChess failure mode is exactly the
  one our network hit today: positions where the term applies are rare in game data, the fit drives
  the coefficient to near zero, and the term does nothing. If a table is fitted it needs positions
  selected *for* attacks, which is a data-generation job, not a tuning job.
* **Choosing between these on published Elo.** Every figure above is either absent or comes from an
  engine unlike ours. The cost column is measured and ours; the value column is neither.

## 6. What I would do with one slot

Mobility and attacker-count king safety **together**, sharing one ray walk, screened as a pair —
because they are the two terms whose absence the round-85/87/88/90 traces actually point at, because
their combined cost is close to mobility's alone rather than double it, and because our existing
king-danger term is gated off whenever the king has two shield pawns
(`KING_DANGER_SHELTERED_PAWNS`), which is most of the time.

Second choice, and much cheaper to try: **rook on 7th, connected rooks and passed-pawn king
distance together**, all three computable from data the first pass in `fasteval.evaluate` already
has, with no ray walk at all. Nobody has measured them and they are close to free, which is a better
risk profile than anything on this page.

**Neither recommendation is evidence that either will gain Elo.** Four static metrics said the
network would gain Elo today and it lost 67. What this document establishes is *cost*, which is
measurable without a screen, and *applicability*, which is a property of our code. Value still needs
the box.
