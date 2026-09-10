import chess, chess.engine
SF="/home/lkmsdx/.local/opt/stockfish/stockfish"
start="rnbqk2r/ppp1ppbp/6p1/8/3PP3/2P1B3/P4PPP/R2QKBNR b KQkq - 2 7"
san="""O-O Bc4 Qd7 Ne2 Nc6 O-O Rd8 Qb3 e6 Bd3 b6 a4 Bb7 a5 Ne5 Bb5 Bc6 c4 Ng4 Bg5 Bxb5 cxb5 Bf6
Bxf6 Nxf6 f3 c6 bxc6 Qxc6 Rfc1 Qb7 Qb5 Rac8 axb6 axb6 Rc5 Ra8 Rb1 Nd7 Rcc1 h6 Qb3 Ra5 Nf4 Rc8
Nxg6 Rxc1+ Rxc1 fxg6 Qxe6+ Kg7 Qe7+ Kg8 Qd8+ Nf8 Rc7 Ra1+ Kf2 Ra8 Qe7 Qxc7 Qxc7""".split()
own={7:-5,8:-4,9:-4,10:-4,11:0,12:10,13:9,14:0,15:-7,16:-4,17:-10,18:-16,19:-18,20:-17,
     21:-19,22:-15,23:-9,24:-7,25:-2,26:-9,27:-11,28:-11,29:-21,30:-85,31:-100,32:-82,
     33:-68,34:-285,35:-403,36:-425,37:-465}
eng=chess.engine.SimpleEngine.popen_uci(SF); eng.configure({"Threads":1,"Hash":64})
b=chess.Board(start)
print(f"{'mv':>3} {'played':>7} {'ours':>7} {'SF':>7} {'gap':>7}  SF best"); print("-"*54)
for m in san:
    if b.turn==chess.BLACK and b.fullmove_number in own:
        i=eng.analyse(b,chess.engine.Limit(depth=18)); sc=i["score"].black()
        best=b.san(i["pv"][0]) if i.get("pv") else "?"
        v=("M%d"%sc.mate()) if sc.is_mate() else sc.score()
        o=own[b.fullmove_number]
        gap="" if sc.is_mate() else f"{o-v:+d}"
        print(f"{b.fullmove_number:>3} {b.san(b.parse_san(m)):>7} {o:>+7} {str(v):>7} {gap:>7}  {best}",flush=True)
    b.push_san(m)
eng.quit()
