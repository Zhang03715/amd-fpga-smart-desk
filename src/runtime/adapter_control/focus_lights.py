"""Deterministic horizontal LED countdown plan; no hardware access."""
import math
HORIZONTAL=tuple(range(30,44))
def plan(timer):
    pixels=[(0,0,0)]*60
    state=timer.get('state','idle');total=timer.get('total_seconds',0);remaining=timer.get('remaining_seconds',0)
    if state not in ('running','paused') or total<=0 or remaining<=0:return pixels,0
    count=max(1,min(len(HORIZONTAL),math.ceil(len(HORIZONTAL)*min(remaining,total)/total)))
    color=(0,255,80) if timer.get('phase')=='rest' else (255,170,50)
    for index in HORIZONTAL[:count]:pixels[index]=color
    return pixels,count
