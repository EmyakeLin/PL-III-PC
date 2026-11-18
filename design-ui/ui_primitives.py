from pathlib import Path
from html import escape

OUT = Path(__file__).parent
C = dict(bg='#E7E7DE', paper='#F7F6EF', white='#FFFEF9', ink='#243D39', muted='#687770', line='#C8CEC3', green='#246455', pale='#E0EAE1', red='#A24B39', rose='#F2E3DC', blue='#447A97', gold='#94713B')
parts = []
def emit(s): parts.append(s)
def text(x,y,s,size=16,color='ink',weight=400):
    emit(f'<text x="{x}" y="{y}" font-size="{size}" fill="{C.get(color,color)}" font-weight="{weight}">{escape(str(s))}</text>')
def box(x,y,w,h,fill='white',stroke='line',cut=0):
    right=x+w; bottom=y+h; near=x+cut; far=right-cut; topcut=y+cut; bottomcut=bottom-cut
    if cut: emit(f'<path d="M {near} {y} H {right} V {bottomcut} L {far} {bottom} H {x} V {topcut} Z" fill="{C[fill]}" stroke="{C[stroke]}"/>')
    else: emit(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{C[fill]}" stroke="{C[stroke]}"/>')
def line(x,y,x2,y2,color='line',width=1): emit(f'<path d="M{x} {y} L{x2} {y2}" stroke="{C[color]}" stroke-width="{width}" fill="none"/>')
def button(x,y,label,w=160,kind='normal'):
    fill={'primary':'green','danger':'red','disabled':'bg','normal':'white','selected':'pale'}[kind]
    color='white' if kind in ['primary','danger'] else 'muted' if kind=='disabled' else 'ink'
    box(x,y,w,44,fill,fill if kind in ['primary','danger'] else 'line',8)
    labelx=x+16; labely=y+28
    text(labelx,labely,label,16,color,600)
def lines(x,y,rows,size=16,color='muted',gap=27):
    for index,row in enumerate(rows):
        baseline=y+index*gap
        text(x,baseline,row,size,color)
def badge(x,y,label,color='green',w=100):
    box(x,y,w,26,'pale' if color=='green' else 'rose' if color=='red' else 'paper','line')
    tx=x+8; ty=y+18
    text(tx,ty,label,13,color,600)
def icon(x,y,kind='斩击',color='green'):
    shapes={'斩击':'M3 19 L19 3 M5 13 L11 19 M3 21 L7 17','突刺':'M3 21 L20 4 M10 4 H20 V14','打击':'M6 3 H18 V10 H6 Z M12 10 V22','招架':'M3 3 H21 V12 L12 22 L3 12 Z','闪避':'M2 8 L10 2 L7 12 M12 14 L21 8 L18 21'}
    emit(f'<path transform="translate({x} {y})" d="{shapes.get(kind,shapes["斩击"])}" fill="none" stroke="{C[color]}" stroke-width="2" stroke-linejoin="round"/>')
def crest(x,y,size=100,color='green'):
    emit(f'<g transform="translate({x} {y}) scale({size/100})" fill="none" stroke="{C[color]}"><path d="M50 3 L96 50 L50 97 L4 50 Z" stroke-width="1"/><path d="M50 18 L80 50 L50 82 L20 50 Z M50 18 V82 M20 50 H80" stroke-width="2"/><path d="M35 35 L65 65 M65 35 L35 65" stroke-width="5"/></g>')
def frame(index,title,sub):
    col=index%3; row=index//3; x=48+col*1220; y=160+row*860
    emit(f'<g id="screen-{index+1:02}" transform="translate({x} {y})">')
    text(0,-30,f'{index+1:02}  {title}',24,'ink',700); text(0,-7,sub,14,'muted')
    box(0,0,1180,760,'paper','line')
    box(0,0,1180,64,'white','line'); crest(20,13,36)
    text(72,39,'光点计划  III',23,'ink',700)
def end(note):
    line(24,710,1156,710); text(24,739,note,14,'muted'); emit('</g>')
def section(x,y,title,detail=''):
    text(x,y,title,22,'ink',700)
    if detail: text(x,y+26,detail,14,'muted')
def stat(x,y,name,hp,maxhp,light,maxlight,extra='',enemy=False):
    accent='red' if enemy else 'green'
    box(x,y,218,132,'white','line',8); text(x+16,y+27,name,19,accent,700)
    text(x+16,y+53,f'生命  {hp} / {maxhp}',15); box(x+16,y+63,184,5,'bg','bg'); box(x+16,y+63,184*hp/maxhp,5,accent,accent)
    text(x+16,y+91,f'光点  {light} / {maxlight}',14,'blue'); text(x+16,y+115,extra,13,'muted')
def card(x,y,name,owner,cost,dice,selected=False):
    box(x,y,200,216,'pale' if selected else 'white','green' if selected else 'line',8)
    text(x+14,y+27,name,20,'ink',700); text(x+14,y+50,owner,13,'muted'); badge(x+143,y+35,f'{cost} 费',w=43)
    line(x+14,y+65,x+186,y+65)
    for index,(kind,roll,damage) in enumerate(dice):
        dy=y+80+index*40
        icon(x+13,dy,kind); text(x+45,dy+16,kind+' '+roll,14); text(x+45,dy+34,damage,12,'red' if '伤害' in damage else 'muted')
    text(x+14,y+198,'查看技能  ↗',13,'green')

