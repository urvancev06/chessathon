# Platform log — round 74 vs Zagreus 5.0 (won by checkmate)

Stored so claims drawn from it can be re-checked. Ready in 34.1 s, numba 33.2 s, 0 phases skipped.

Replaced 9 September: this file previously held the operator's formatted table rather than the raw
log, so it was the only one of the four that did not match the `m … d … n … t … s … h … c …`
pattern the others use. `chessathon-5f`'s parser found no move lines in it. The raw log is below,
so the four logs are now a machine-readable set.

Two things this game settles, both against claims in `handoff/FINDING-closed-positions-round73.md`:
per-move soft-budget usage is median 65% with 27% of moves running past the soft budget, not the
"45-60% on nearly every move" claimed; and the depth collapse over the last four moves (7, 5, 3, 1)
is a forced mate found at depth 1 with the clock *rising*, not clock panic.

```
AI CHESSATHON MATCH LOG
=======================

MATCH
  Round          Rated 74
  Team           Mikhail LeTal
  Colour         Black
  Opponent       Zagreus 5.0
  Opening        Caro-Kann Advance
  Start FEN      rn1qkbnr/pp3ppp/2p1p3/3pPb2/3P4/5N2/PPPN1PPP/R1BQKB1R b KQkq - 1 5
  You moved      First
  Machine        w-de0e76
  Finished       2026-09-08 20:19:10 UTC
  Match ID       cf8ea64c-4490-4e21-a379-02b92f1fec3e

INIT
  Ready in       34.1 s
  Budget         90.0 s
  Used           38 percent

CLOCK
  Base           120.0 s plus 0.5 s per move
  Moves          70
  Time used      145.2 s
  Slowest        4.9 s on move 6
  Fastest        0.0 s on move 70
  Average        2.1 s
  Left at end    9.8 s

RESULT
  Won by checkmate
  Game lasted 284.8 s

MOVES
    #  move          time     clock left
    1  Qb6           1.8 s      118.7 s
    2  Nd7           1.7 s      117.4 s
    3  f6            4.1 s      113.8 s
    4  Qc7           3.3 s      111.0 s
    5  O-O-O         4.4 s      107.1 s
    6  fxe5          4.9 s      102.8 s
    7  c5            1.6 s      101.6 s
    8  Nh6           1.6 s      100.6 s
    9  Bxd3          1.9 s       99.1 s
   10  Qb6           3.0 s       96.6 s
   11  Kb8           2.9 s       94.1 s
   12  Qxa5          1.5 s       93.2 s
   13  Re8           3.6 s       90.1 s
   14  g6            3.0 s       87.6 s
   15  b6            1.5 s       86.6 s
   16  Bg7           2.0 s       85.1 s
   17  c4            2.4 s       83.2 s
   18  Nf5           2.3 s       81.4 s
   19  Rhf8          1.4 s       80.5 s
   20  h5            1.8 s       79.2 s
   21  b5            4.3 s       75.5 s
   22  Bh6           1.7 s       74.2 s
   23  Nxh6          3.6 s       71.2 s
   24  Nf5           3.4 s       68.3 s
   25  b4            1.5 s       67.3 s
   26  a5            2.8 s       65.0 s
   27  Nb6           1.6 s       63.9 s
   28  Rf7           1.5 s       62.8 s
   29  Rc8           2.8 s       60.5 s
   30  Na4           1.3 s       59.7 s
   31  Re7           2.2 s       58.0 s
   32  c3            1.4 s       57.1 s
   33  Rc4           2.8 s       54.8 s
   34  Rxc3          3.2 s       52.0 s
   35  bxc3          1.6 s       51.0 s
   36  Rb7           4.5 s       47.0 s
   37  Rb2           1.8 s       45.7 s
   38  Ng7           1.4 s       44.8 s
   39  Rxa2          1.2 s       44.1 s
   40  Kb7           1.8 s       42.8 s
   41  Ra3           1.3 s       42.0 s
   42  Nb2           4.0 s       38.5 s
   43  Rb3           1.5 s       37.4 s
   44  c2            1.3 s       36.7 s
   45  Rxf3          1.7 s       35.4 s
   46  Nd3           1.1 s       34.8 s
   47  c1=Q          3.9 s       31.4 s
   48  Nxc1          2.6 s       29.3 s
   49  a4            1.4 s       28.4 s
   50  a3            1.4 s       27.6 s
   51  Kc6           1.9 s       26.2 s
   52  a2            4.1 s       22.6 s
   53  Nd3+          3.9 s       19.2 s
   54  a1=Q          1.0 s       18.7 s
   55  Qxd4          0.8 s       18.4 s
   56  Qxe5+         1.0 s       17.9 s
   57  h4            1.2 s       17.2 s
   58  Qh5+          1.1 s       16.6 s
   59  Nf4           1.4 s       15.8 s
   60  Nxg6+         1.4 s       14.9 s
   61  d4            0.9 s       14.5 s
   62  d3            1.1 s       13.8 s
   63  exf5          1.2 s       13.1 s
   64  Kd5           3.3 s       10.3 s
   65  d2            2.6 s        8.2 s
   66  d1=Q          0.7 s        8.0 s
   67  Kc6           0.1 s        8.5 s
   68  Nf4           0.1 s        8.9 s
   69  Qd4+          0.0 s        9.4 s
   70  Qd6#          0.0 s        9.8 s

OUTPUT
  4,555 bytes on stderr

  init 33725 ms Mikhail LeTal 1.0.0 jit 33.2s budget 70s skipped 0 nps 456935
  m d8b6 d 9/26 n 836251 nps 458672 t 1825 s 3396 h 10189 c 120000
  m b8d7 d 10/25 n 803941 nps 460968 t 1746 s 3363 h 10089 c 118674
  m f7f6 d 10/26 n 1861212 nps 451579 t 4123 s 3407 h 10221 c 117427
  m b6c7 d 10/28 n 1573158 nps 477025 t 3300 s 3314 h 9942 c 113802
  m e8c8 d 10/33 n 2059354 nps 469653 t 4387 s 3317 h 9951 c 111001
  m f6e5 d 10/28 n 2280109 nps 469748 t 4856 s 3215 h 9645 c 107114
  m c6c5 d 9/24 n 737495 nps 455683 t 1620 s 3173 h 9519 c 102757
  m g8h6 d 9/27 n 748744 nps 475553 t 1576 s 3143 h 9429 c 101636
  m f5d3 d 9/27 n 942497 nps 484140 t 1948 s 3189 h 9567 c 100559
  m c7b6 d 9/26 n 1481479 nps 488586 t 3034 s 3149 h 9447 c 99110
  m c8b8 d 9/27 n 1488739 nps 506135 t 2943 s 3155 h 9465 c 96575
  m b6a5 d 12/25 n 721316 nps 494038 t 1461 s 3085 h 9255 c 94130
  m d8e8 d 12/26 n 1797091 nps 501469 t 3585 s 3136 h 9407 c 93167
  m g7g6 d 11/27 n 1492406 nps 494415 t 3020 s 3045 h 9135 c 90081
  m b7b6 d 10/26 n 755719 nps 505419 t 1497 s 3049 h 9146 c 87560
  m f8g7 d 10/26 n 1009752 nps 510858 t 1978 s 3019 h 9056 c 86562
  m c5c4 d 11/27 n 1193499 nps 505550 t 2362 s 3054 h 9162 c 85083
  m h6f5 d 11/24 n 1173527 nps 504821 t 2326 s 2996 h 8988 c 83219
  m h8f8 d 10/25 n 699325 nps 509811 t 1373 s 3021 h 9062 c 81392
  m h7h5 d 10/24 n 905315 nps 502617 t 1803 s 2993 h 8978 c 80518
  m b6b5 d 10/28 n 2082070 nps 489632 t 4254 s 3035 h 9106 c 79214
  m g7h6 d 9/25 n 861535 nps 498389 t 1730 s 2910 h 8731 c 75459
  m f5h6 d 12/26 n 1829349 nps 512037 t 3574 s 2954 h 8863 c 74227
  m h6f5 d 11/24 n 1705990 nps 507050 t 3366 s 2848 h 8545 c 71152
  m b5b4 d 10/26 n 747525 nps 507821 t 1474 s 2833 h 8500 c 68285
  m a7a5 d 11/24 n 1399882 nps 497538 t 2815 s 2799 h 8396 c 67310
  m d7b6 d 11/24 n 789028 nps 484830 t 1629 s 2802 h 8405 c 64993
  m f8f7 d 12/24 n 727240 nps 476222 t 1529 s 2760 h 8279 c 63863
  m e8c8 d 12/24 n 1412675 nps 499458 t 2830 s 2811 h 8433 c 62834
  m b6a4 d 11/23 n 631769 nps 473444 t 1336 s 2721 h 8164 c 60502
  m f7e7 d 11/24 n 1035015 nps 477626 t 2168 s 2781 h 8342 c 59665
  m c4c3 d 11/21 n 716592 nps 503401 t 1425 s 2714 h 8141 c 57995
  m c8c4 d 11/23 n 1353238 nps 483740 t 2799 s 2772 h 8315 c 57068
  m c4c3 d 11/23 n 1530840 nps 475723 t 3219 s 2676 h 8027 c 54768
  m b4c3 d 12/22 n 781874 nps 497862 t 1572 s 2656 h 7969 c 52047
  m e7b7 d 12/23 n 2131447 nps 475788 t 4481 s 2610 h 7829 c 50975
  m b7b2 d 11/21 n 917056 nps 503971 t 1821 s 2529 h 7588 c 46992
  m f5g7 d 11/22 n 678950 nps 500866 t 1357 s 2469 h 7407 c 45670
  m b2a2 d 10/22 n 629002 nps 516575 t 1219 s 2527 h 7580 c 44811
  m b8b7 d 12/22 n 918457 nps 512619 t 1793 s 2492 h 7477 c 44091
  m a2a3 d 11/22 n 666006 nps 514983 t 1295 s 2532 h 7597 c 42797
  m a4b2 d 14/26 n 2091414 nps 518858 t 4032 s 2492 h 7478 c 42000
  m a3b3 d 11/23 n 759040 nps 499949 t 1520 s 2417 h 7250 c 38466
  m c3c2 d 14/24 n 649723 nps 513974 t 1265 s 2363 h 7089 c 37445
  m b3f3 d 15/24 n 932228 nps 534018 t 1747 s 2429 h 7288 c 36679
  m b2d3 d 15/27 n 618172 nps 564848 t 1096 s 2360 h 7080 c 35431
  m c2c1q d 15/32 n 2030788 nps 521547 t 3895 s 2440 h 7321 c 34834
  m d3c1 d 15/25 n 1430153 nps 543115 t 2635 s 2240 h 6721 c 31438
  m a5a4 d 14/25 n 771081 nps 568113 t 1358 s 2222 h 6666 c 29302
  m a4a3 d 15/27 n 733684 nps 530255 t 1385 s 2168 h 6505 c 28442
  m b7c6 d 14/25 n 993679 nps 530764 t 1873 s 2227 h 6681 c 27556
  m a3a2 d 16/30 n 2063658 nps 503808 t 4098 s 2135 h 6406 c 26181
  m c1d3 d 14/28 n 2019140 nps 524309 t 3852 s 2002 h 5646 c 22582
  m a2a1q d 14/26 n 531431 nps 525795 t 1012 s 1763 h 4807 c 19229
  m a1d4 d 13/26 n 450808 nps 536467 t 842 s 1828 h 4679 c 18716
  m d4e5 d 12/25 n 504560 nps 505154 t 1000 s 1802 h 4593 c 18373
  m h5h4 d 13/23 n 613053 nps 533197 t 1152 s 1877 h 4468 c 17872
  m e5h5 d 14/24 n 607720 nps 560141 t 1086 s 1822 h 4305 c 17219
  m d3f4 d 14/23 n 845228 nps 613929 t 1378 s 1774 h 4158 c 16632
  m f4g6 d 12/26 n 737516 nps 532291 t 1387 s 1700 h 3938 c 15753
  m d5d4 d 13/22 n 458383 nps 519916 t 883 s 1626 h 3716 c 14865
  m d4d3 d 9/18 n 700707 nps 611513 t 1147 s 1594 h 3620 c 14480
  m e6f5 d 9/18 n 721534 nps 587385 t 1230 s 1540 h 3458 c 13832
  m c6d5 d 11/22 n 1933824 nps 590462 t 3276 s 1479 h 3275 c 13101
  m d3d2 d 9/20 n 1630720 nps 631803 t 2582 s 1248 h 2581 c 10324
  m d2d1q d 8/18 n 448440 nps 645692 t 696 s 1074 h 2060 c 8240
  m d5c6 d 7/16 n 51155 nps 611519 t 85 s 1058 h 2011 c 8043
  m g6f4 d 5/14 n 52206 nps 554343 t 95 s 1092 h 2114 c 8457
  m d1d4 d 3/10 n 2953 nps 434623 t 8 s 1126 h 2215 c 8861
  m d4d6 d 1/4 n 60 nps 56252 t 2 s 1167 h 2338 c 9352

Email hello@aichessathon.com with this file if anything here is unclear.
```
