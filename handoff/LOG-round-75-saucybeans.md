# Platform log — round 75 vs SaucyBeans (draw by threefold repetition)

Stored so claims drawn from it can be re-checked. Ready in 33.6 s, numba 32.7 s, 0 phases skipped.
Stockfish depth 57 scores the position before our first Rb4 at 0.00: the repetition was correct.

```
AI CHESSATHON MATCH LOG
=======================

MATCH
  Round          Rated 75
  Team           Mikhail LeTal
  Colour         White
  Opponent       SaucyBeans
  Opening        Caro-Kann Classical
  Start FEN      rn1qkbnr/pp2pppp/2p3b1/8/3P4/4B1N1/PPP2PPP/R2QKBNR b KQkq - 4 6
  You moved      Second
  Machine        w-ed4b51
  Finished       2026-09-08 21:16:27 UTC
  Match ID       71caf936-ed73-4267-a441-9087318832cf

INIT
  Ready in       33.6 s
  Budget         90.0 s
  Used           37 percent

CLOCK
  Base           120.0 s plus 0.5 s per move
  Moves          54
  Time used      124.8 s
  Slowest        8.1 s on move 47
  Fastest        0.9 s on move 52
  Average        2.3 s
  Left at end    22.2 s

RESULT
  Drawn by threefold repetition
  Game lasted 242.0 s

MOVES
    #  move          time     clock left
    1  Qc1           2.2 s      118.3 s
    2  Nf3           1.8 s      117.0 s
    3  Bd2           1.6 s      115.8 s
    4  c3            5.9 s      110.5 s
    5  Bc4           1.6 s      109.3 s
    6  O-O           2.3 s      107.5 s
    7  cxd4          1.9 s      106.1 s
    8  Re1           2.5 s      104.1 s
    9  a4            3.0 s      101.5 s
   10  Ne4           1.9 s      100.2 s
   11  b3            1.9 s       98.8 s
   12  Qd1           1.7 s       97.5 s
   13  Rc1           1.7 s       96.3 s
   14  Nc3           1.5 s       95.3 s
   15  Bxc3          2.0 s       93.8 s
   16  Ra1           3.2 s       91.2 s
   17  Qd3           2.1 s       89.6 s
   18  Rad1          2.0 s       88.0 s
   19  Qe2           2.4 s       86.1 s
   20  g3            3.0 s       83.6 s
   21  Ne5           1.4 s       82.7 s
   22  Nxg6          3.2 s       80.0 s
   23  Qd2           2.1 s       78.3 s
   24  Bb5           2.4 s       76.4 s
   25  Bxc6          2.0 s       75.0 s
   26  Bxb4          1.8 s       73.7 s
   27  Qxb4+         2.7 s       71.4 s
   28  Rc1           3.5 s       68.4 s
   29  Rxc6          1.9 s       67.1 s
   30  h4            2.5 s       65.1 s
   31  Rc5           3.0 s       62.6 s
   32  Rb5+          4.2 s       58.9 s
   33  Rc1           3.2 s       56.2 s
   34  Rc6+          1.4 s       55.3 s
   35  Re5           1.3 s       54.5 s
   36  Re3           1.3 s       53.7 s
   37  Rxd3          1.7 s       52.5 s
   38  Rc7+          4.0 s       49.0 s
   39  Rxf7          3.2 s       46.3 s
   40  Kg2           1.4 s       45.4 s
   41  Rc7           1.3 s       44.6 s
   42  Rc5           1.9 s       43.2 s
   43  Rb5           1.2 s       42.5 s
   44  hxg5          1.8 s       41.2 s
   45  g6            1.7 s       40.0 s
   46  g4            1.2 s       39.3 s
   47  Kh2           8.1 s       31.7 s
   48  g5            2.3 s       29.9 s
   49  a5            2.2 s       28.2 s
   50  Rb4           2.3 s       26.4 s
   51  Rb7           1.8 s       25.1 s
   52  Rb4           0.9 s       24.7 s
   53  Rb7           1.1 s       24.1 s
   54  Rb4           2.5 s       22.2 s

OUTPUT
  3,551 bytes on stderr

  init 33253 ms Mikhail LeTal 1.0.0 jit 32.7s budget 70s skipped 0 nps 437620
  m d1c1 d 9/22 n 934335 nps 418507 t 2234 s 3396 h 10189 c 120000
  m g1f3 d 9/21 n 749921 nps 422660 t 1776 s 3353 h 10059 c 118264
  m e3d2 d 9/22 n 655062 nps 398554 t 1645 s 3396 h 10188 c 116988
  m c2c3 d 10/26 n 2353364 nps 400048 t 5884 s 3366 h 10099 c 115841
  m f1c4 d 9/23 n 691290 nps 419983 t 1648 s 3303 h 9908 c 110456
  m e1g1 d 9/27 n 977374 nps 432188 t 2263 s 3273 h 9818 c 109307
  m c3d4 d 10/28 n 834803 nps 431287 t 1937 s 3303 h 9908 c 107543
  m f1e1 d 9/24 n 1124277 nps 445823 t 2523 s 3264 h 9791 c 106104
  m a2a4 d 9/25 n 1344599 nps 444175 t 3029 s 3287 h 9861 c 104080
  m g3e4 d 9/25 n 850789 nps 453977 t 1876 s 3217 h 9650 c 101550
  m b2b3 d 8/27 n 874436 nps 457529 t 1913 s 3258 h 9773 c 100173
  m c1d1 d 8/24 n 801887 nps 462860 t 1734 s 3217 h 9652 c 98759
  m a1c1 d 8/25 n 785901 nps 466292 t 1687 s 3264 h 9792 c 97523
  m e4c3 d 8/26 n 702134 nps 454176 t 1548 s 3229 h 9687 c 96335
  m d2c3 d 10/25 n 823220 nps 422205 t 1952 s 3283 h 9849 c 95286
  m c1a1 d 10/27 n 1398103 nps 442909 t 3158 s 3239 h 9717 c 93833
  m d1d3 d 9/25 n 894322 nps 426827 t 2097 s 3244 h 9734 c 91174
  m a1d1 d 8/26 n 913062 nps 448546 t 2037 s 3195 h 9584 c 89576
  m d3e2 d 10/25 n 1013501 nps 420914 t 2410 s 3235 h 9705 c 88038
  m g2g3 d 9/26 n 1287504 nps 430522 t 2992 s 3173 h 9520 c 86126
  m f3e5 d 9/25 n 649672 nps 450548 t 1444 s 3183 h 9548 c 83633
  m e5g6 d 9/26 n 1410098 nps 436986 t 3229 s 3151 h 9454 c 82689
  m e2d2 d 9/23 n 977574 nps 456954 t 2141 s 3152 h 9456 c 79959
  m c4b5 d 9/22 n 1124223 nps 472276 t 2382 s 3095 h 9286 c 78317
  m b5c6 d 11/25 n 920595 nps 471513 t 1954 s 3124 h 9373 c 76434
  m c3b4 d 11/22 n 863039 nps 482912 t 1789 s 3072 h 9217 c 74979
  m d2b4 d 13/25 n 1353534 nps 492971 t 2747 s 3124 h 9371 c 73689
  m d1c1 d 14/25 n 1825133 nps 519402 t 3515 s 3040 h 9121 c 71441
  m c1c6 d 12/21 n 940694 nps 504624 t 1865 s 3026 h 9078 c 68424
  m h2h4 d 11/21 n 1241793 nps 507089 t 2450 s 2973 h 8920 c 67058
  m c6c5 d 12/21 n 1505386 nps 497274 t 3029 s 2998 h 8995 c 65107
  m c5b5 d 12/24 n 2015108 nps 483142 t 4172 s 2897 h 8691 c 62577
  m e1c1 d 12/23 n 1652915 nps 509676 t 3244 s 2848 h 8544 c 58904
  m c1c6 d 11/25 n 724506 nps 523346 t 1386 s 2734 h 8201 c 56158
  m b5e5 d 11/23 n 672749 nps 518185 t 1300 s 2797 h 8390 c 55271
  m e5e3 d 11/21 n 660230 nps 520473 t 1270 s 2762 h 8285 c 54471
  m e3d3 d 15/23 n 896274 nps 543925 t 1649 s 2834 h 8502 c 53700
  m c6c7 d 14/25 n 2224022 nps 553206 t 4021 s 2782 h 8345 c 52549
  m c7f7 d 14/25 n 1824081 nps 567532 t 3215 s 2727 h 8182 c 49027
  m g1g2 d 12/23 n 779011 nps 545601 t 1429 s 2598 h 7794 c 46310
  m f7c7 d 12/23 n 737010 nps 565422 t 1305 s 2662 h 7984 c 45380
  m c7c5 d 14/23 n 1071574 nps 571980 t 1875 s 2621 h 7864 c 44574
  m c5b5 d 14/22 n 667301 nps 547469 t 1220 s 2666 h 7997 c 43198
  m h4g5 d 15/23 n 1016532 nps 572882 t 1776 s 2628 h 7883 c 42477
  m g5g6 d 15/22 n 982373 nps 574043 t 1713 s 2681 h 8042 c 41200
  m g3g4 d 16/25 n 746113 nps 616193 t 1212 s 2613 h 7839 c 39986
  m g2h2 d 16/29 n 4878848 nps 602003 t 8106 s 2701 h 8104 c 39272
  m g4g5 d 15/25 n 1368943 nps 599108 t 2286 s 2254 h 6762 c 31666
  m a4a5 d 15/25 n 1320459 nps 609739 t 2167 s 2258 h 6774 c 29879
  m b5b4 d 16/27 n 1231244 nps 537930 t 2290 s 2154 h 6461 c 28210
  m b4b7 d 15/28 n 1026295 nps 579729 t 1772 s 2151 h 6454 c 26419
  m b7b4 d 17/29 n 470825 nps 505082 t 933 s 2066 h 6199 c 25147
  m b4b7 d 25/25 n 786763 nps 738993 t 1066 s 2154 h 6178 c 24712
  m b7b4 d 19/35 n 1167042 nps 475172 t 2457 s 2114 h 6036 c 24145

Email hello@aichessathon.com with this file if anything here is unclear.
```
