"""사람 작업 자세 v2 — Drive 참고 그림(worker_character_only.svg) 기반.
참고 그림의 머리·몸통·팔(모니터 쪽을 보는 3/4 뒷모습)을 그대로 쓰고,
서 있는 다리만 기존 앉은 다리로 바꾼다. 팔은 어깨를 축으로 돌려 손이 키보드 위에 오게 한다.
좌표: 참고 그림 px (900×1100). 색은 앱 팔레트 키(var(--key))."""
import json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
T = json.load(open(os.path.join(OUT, "human_traced.json")))
PAL = T["pal"]

OLD_PPU = (1326 / 28) / 1.182          # 기존 작업 그림 px/단위
HEAD_RATIO = 0.908                       # 참고 머리 외곽 / 기존 머리 외곽 (폭·높이 평균)
PPU = OLD_PPU * HEAD_RATIO               # 참고 그림 px/단위
K = 0.9
P = dict(anchor=[330, 690], near_t=[5.6, -6.7], far_t=[7.5, -6.2],
         hem_up=40, leg_dx=0, leg_dy=0, leg_rot=-14)
if len(sys.argv) > 1 and sys.argv[1]: P.update(json.loads(sys.argv[1]))
AX, AY = P["anchor"]
def seat_to_px(u, v): return (AX + u / K * PPU, AY + v / K * PPU)
NEAR_T, FAR_T = seat_to_px(*P["near_t"]), seat_to_px(*P["far_t"])

# 팔: 어깨→팔꿈치→손목을 둥근 굵은 선(소매)으로 새로 긋고, 참고 그림의 손 모양을 손목 끝에 붙인다.
REF_HANDS = {  # 참고 그림 손 path, 손 중심, 참고 그림 팔뚝 각도(도)
  "near": ("M558 477 Q574 465 593 473 Q609 465 619 480 Q630 497 616 507 Q619 524 601 529 Q580 544 554 537 L540 513Z", (582, 505), -14),
  "far":  ("M617 432 Q642 418 661 432 Q678 429 686 442 Q685 456 671 462 Q653 477 630 474 L606 462Z", (645, 449), -20)}
def arm(which, sh, el, hand_c, w):
    path, c, ref_ang = REF_HANDS[which]
    ang = math.degrees(math.atan2(hand_c[1] - el[1], hand_c[0] - el[0]))
    L = math.hypot(hand_c[0] - el[0], hand_c[1] - el[1]); ux, uy = (hand_c[0] - el[0]) / L, (hand_c[1] - el[1]) / L
    wr = (hand_c[0] - ux * P["wrist_back"], hand_c[1] - uy * P["wrist_back"])
    d = f"M{sh[0]:.1f},{sh[1]:.1f} Q{el[0]:.1f},{el[1]:.1f} {wr[0]:.1f},{wr[1]:.1f}"
    sleeve = (f'<path d="{d}" fill="none" stroke="var(--outline)" stroke-width="{w + P["sleeve_ol"]}"/>'
              f'<path d="{d}" fill="none" stroke="var(--shirt)" data-key="shirt" stroke-width="{w}"/>')
    hand = (f'<g transform="translate({hand_c[0] - c[0]:.1f},{hand_c[1] - c[1]:.1f}) rotate({(ang - ref_ang) * P["hand_mix"]:.1f},{c[0]},{c[1]})">'
            f'<path d="{path}" fill="var(--skin)" data-key="skin"/></g>')
    return sleeve + hand
P.setdefault("near_sh", [300, 455]); P.setdefault("near_el", [392, 528]); P.setdefault("far_sh", [455, 450]); P.setdefault("far_el", [515, 520])
P.setdefault("hand_mix", 0.35); P.setdefault("sleeve_ol", 26); P.setdefault("sleeve_w", 54); P.setdefault("wrist_back", 30)
O = 'stroke="var(--outline)"'
def F(key): return f'fill="var(--{key})" data-key="{key}"'
hu = P["hem_up"]
legs_g = (f'<g id="legs" transform="translate({AX + P["leg_dx"]},{AY + P["leg_dy"]}) rotate({P["leg_rot"]}) scale({HEAD_RATIO}) '
          f'translate({-515},{-822})">{"".join(T["legs"])}</g>')
hair_back = f'<path d="M268 357 Q214 378 175 337 Q147 304 162 265 Q174 238 199 214 Q198 138 245 105 Q284 68 352 75 Q423 67 468 117 Q519 132 529 201 Q555 234 551 286 Q548 333 507 353 Q482 370 444 354 Q393 398 344 365 Q307 397 268 357Z" {F("hair")}/>'
neck = f'<path d="M369 340 L376 406 Q423 436 457 398 L439 326Z" {F("skin")}/>'
body = (f'<path d="M323 385 Q286 394 267 432 Q250 465 251 531 L{248} {626-hu} Q281 {672-hu} 355 {683-hu} '
        f'Q451 {700-hu} 494 {650-hu} L476 496 Q465 425 434 398 Q414 430 388 431 Q352 422 323 385Z" {F("shirt")}/>'
        '')
face = (f'<path d="M349 201 Q387 154 445 170 Q493 182 510 237 Q522 268 510 295 Q498 320 480 337 Q462 361 414 368 Q375 366 348 340 Q324 311 322 275 Q322 237 349 201Z" {F("skin")}/>'
        f'<path d="M292 219 Q303 145 382 125 Q436 117 471 164 Q459 209 426 235 Q382 261 336 261 Q324 279 323 301 Q299 281 292 219Z" {F("hair")}/>'
        f'<path d="M277 289 Q247 341 285 356 Q314 366 342 338" fill="none" stroke-width="12"/>'
        f'<path d="M326 266 Q297 251 290 277 Q287 307 318 318 Q337 317 338 296" {F("skin")}/>'
        f'<ellipse cx="459" cy="258" rx="9" ry="15" fill="var(--outline)" stroke="none"/>'
        f'<path d="M501 274 Q512 278 505 286" fill="none" stroke-width="7"/>'
        f'<path d="M458 306 Q472 325 491 308" fill="none" stroke-width="8"/>')
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 1100" width="900" height="1100">
<style>:root{{{";".join(f"--{k}:{v}" for k, v in PAL.items())}}}</style>
{legs_g}
<g {O} stroke-width="15" stroke-linejoin="round" stroke-linecap="round">
<g id="hair-back">{hair_back}</g>
<g id="arm-far" data-pivot="{P["far_sh"][0]},{P["far_sh"][1]}">{arm("far", P["far_sh"], P["far_el"], FAR_T, P["sleeve_w"])}</g>
<g id="torso">{neck}{body}</g>
<g id="arm-near" data-pivot="{P["near_sh"][0]},{P["near_sh"][1]}">{arm("near", P["near_sh"], P["near_el"], NEAR_T, P["sleeve_w"])}</g>
<g id="head">{face}</g>
</g>
</svg>'''
open(os.path.join(OUT, "human-working-v2.svg"), "w").write(svg)
meta = {"source": "Drive worker_character_only.svg (2026-11-07) + 기존 앉은 다리", "viewBox": [0, 0, 900, 1100],
        "ppu": round(PPU, 3), "kRef": K, "turn": None,
        "anchors": {"seat": [AX, AY], "nearHand": [round(v, 1) for v in NEAR_T], "farHand": [round(v, 1) for v in FAR_T]},
        "drawOrder": ["legs", "hair-back", "arm-far", "torso", "arm-near", "head"], "paletteKeys": list(PAL),
        "params": P}
json.dump(meta, open(os.path.join(OUT, "human-working-v2.meta.json"), "w"), indent=1)
print(json.dumps(meta["anchors"]))
