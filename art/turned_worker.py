"""모니터 쪽(화면 오른쪽 위)으로 몸 전체를 돌린 사람 작업 자세 — 3/4 뒷모습, 앉은 자세.
머리는 Drive 참고 그림(worker_character_only.svg) 그대로. 몸통은 등, 팔·다리는 몸 너머(오른쪽 위)로 뻗음.
좌표: 900×1100, 외곽선 15px (참고 그림과 같음)."""
import os, sys, json
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
PAL = {"outline": "#3a2416", "hair": "#734c3e", "skin": "#fcccb2", "shirt": "#f67668", "pants": "#5a4242", "shoe": "#f8ecd6"}
def F(k): return f'fill="var(--{k})" data-key="{k}"'
N = 'fill="none"'

# ── 다리 (몸 너머로 뻗어 책상 밑으로) : 먼 다리 → 가까운 다리
far_leg = (f'<path d="M478 600 L612 556 Q648 556 652 590 Q652 620 622 630 L640 728 Q646 748 628 752 L600 752 Q588 748 588 730 L574 640 L500 662 Z" {F("pants")}/>'
           f'<path d="M596 738 Q628 726 660 734 Q700 744 712 766 Q716 786 690 790 Q640 794 604 782 Q586 772 590 752 Z" {F("shoe")}/>'
           f'<path d="M612 764 Q650 774 690 770" {N} stroke-width="9"/>')
near_leg = (f'<path d="M440 640 L578 604 Q616 604 620 640 Q620 672 590 682 L606 780 Q610 800 590 804 L562 804 Q548 800 548 782 L536 696 L482 690 Z" {F("pants")}/>'
            f'<path d="M558 790 Q592 778 624 786 Q664 796 676 818 Q680 838 654 842 Q604 846 568 834 Q550 824 554 804 Z" {F("shoe")}/>'
            f'<path d="M576 816 Q614 826 654 822" {N} stroke-width="9"/>')
seat = f'<path d="M262 600 Q244 668 296 700 Q372 724 462 700 Q508 682 508 612 Z" {F("pants")}/>'

# ── 팔 (몸 앞=화면 안쪽에 있어 몸통 뒤에 그림, 몸통 오른쪽 너머로 나옴)
def sleeve(d, w=54):
    return (f'<path d="{d}" {N} stroke="var(--outline)" stroke-width="{w + 26}"/>'
            f'<path d="{d}" {N} stroke="var(--shirt)" data-key="shirt" stroke-width="{w}"/>')
HAND = "M558 477 Q574 465 593 473 Q609 465 619 480 Q630 497 616 507 Q619 524 601 529 Q580 544 554 537 L540 513Z"  # 참고 그림 앞손 (중심 582,505)
def hand(cx, cy, rot): return f'<g transform="translate({cx-582},{cy-505}) rotate({rot},582,505)"><path d="{HAND}" {F("skin")}/></g>'
far_arm = sleeve("M452 452 Q560 470 640 418") + hand(668, 410, -18)
near_arm = sleeve("M420 520 Q520 520 600 462") + hand(628, 452, -22)

# ── 몸통 (등)
torso = (f'<path d="M328 388 Q280 396 262 440 Q244 484 248 548 L252 622 Q300 656 384 656 Q462 652 504 620 L496 520 Q492 452 474 420 Q452 394 420 390 Z" {F("shirt")}/>'
         '')
neck = f'<path d="M369 336 L374 404 Q414 424 452 398 L440 326Z" {F("skin")}/>'
collar = f'<path d="M336 392 Q392 424 452 396" {N} stroke-width="12"/>'

# ── 머리 (참고 그림 그대로)
hair_back = f'<path d="M268 357 Q214 378 175 337 Q147 304 162 265 Q174 238 199 214 Q198 138 245 105 Q284 68 352 75 Q423 67 468 117 Q519 132 529 201 Q555 234 551 286 Q548 333 507 353 Q482 370 444 354 Q393 398 344 365 Q307 397 268 357Z" {F("hair")}/>'
face = (f'<path d="M349 201 Q387 154 445 170 Q493 182 510 237 Q522 268 510 295 Q498 320 480 337 Q462 361 414 368 Q375 366 348 340 Q324 311 322 275 Q322 237 349 201Z" {F("skin")}/>'
        f'<path d="M292 219 Q303 145 382 125 Q436 117 471 164 Q459 209 426 235 Q382 261 336 261 Q324 279 323 301 Q299 281 292 219Z" {F("hair")}/>'
        f'<path d="M277 289 Q247 341 285 356 Q314 366 342 338" {N} stroke-width="12"/>'
        f'<path d="M326 266 Q297 251 290 277 Q287 307 318 318 Q337 317 338 296" {F("skin")}/>'
        f'<ellipse cx="459" cy="258" rx="9" ry="15" fill="var(--outline)" stroke="none"/>'
        f'<path d="M501 274 Q512 278 505 286" {N} stroke-width="7"/>'
        f'<path d="M458 306 Q472 325 491 308" {N} stroke-width="8"/>')

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1100" width="900" height="1100">
<style>:root{{{";".join(f"--{k}:{v}" for k, v in PAL.items())}}}</style>
<g stroke="var(--outline)" stroke-width="15" stroke-linejoin="round" stroke-linecap="round">
<g id="leg-far">{far_leg}</g><g id="leg-near">{near_leg}</g><g id="seat">{seat}</g>
<g id="arm-far">{far_arm}</g><g id="arm-near">{near_arm}</g>
<g id="hair-back">{hair_back}</g>
<g id="torso">{neck}{torso}{collar}</g>
<g id="head">{face}</g>
</g></svg>'''
open(os.path.join(OUT, "human-working-turned.svg"), "w").write(svg)
print("ok")
