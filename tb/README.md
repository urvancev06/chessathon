# Syzygy endgame tablebases, 3 and 4 pieces

70 files, 4.4 MB: perfect play for every position with at most four pieces on the board.
`.rtbw` files answer win, draw or loss; `.rtbz` files give the distance to the next capture or
pawn move, which is what lets a win be converted under the fifty-move rule.

Downloaded from the public mirror at `https://tablebase.lichess.ovh/tables/standard/`
(`3-4-5-wdl/` and `3-4-5-dtz/`, filtered to the files with at most four pieces) on 8 September
2026. Syzygy tables are generated data in a published format, not a program, and the competition
rules name endgame tablebases as permitted alongside opening books.

Five piece tables are far too large: the rook-and-pawn against rook file alone is 15.6 MB and the
full five piece set is about 380 MB, against a 50 MB limit for everything in the zip. So the
Lucena position stays unsolved by lookup and has to be played.

They are packaged only when the zip is built with `--include tb`.
