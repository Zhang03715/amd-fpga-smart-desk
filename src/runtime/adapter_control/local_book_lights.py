"""Select measured physical LED centres for a book, without extrapolating IDs."""
import math


def select_axis(centres, box, axis):
    if len(box) != 4 or any(not math.isfinite(v) for v in box):
        raise ValueError('invalid_box')
    if box[0] >= box[2] or box[1] >= box[3] or axis not in (0, 1):
        raise ValueError('invalid_box_or_axis')
    points = sorted((float(p['xy'][axis]), int(p['index'])) for p in centres)
    if not points:
        raise ValueError('no_measured_leds')
    low, high = box[axis], box[axis+2]
    selected = [i for position, i in points if low <= position <= high]
    if selected:
        return sorted(selected)
    # A thin book between centres is indicated by its two neighbours.
    middle = (low+high)/2
    before = [(p, i) for p, i in points if p < middle]
    after = [(p, i) for p, i in points if p >= middle]
    return sorted({pair[1] for pair in before[-1:]+after[:1]})


def horizontal_mapping(centres, match):
    """Project upright title centreline onto the measured, non-flat LED rail."""
    if match.get('orientation')!='upright':
        audit=match.get('flat_extent_audit') or {}
        if audit.get('status') in ('end_disagreement','insufficient_seams','invalid_band','cuts_title'):
            raise ValueError('flat_spine_extent_unconfirmed')
        box=match['book_box']
        # Cover the span's endpoints too: each measured lamp represents the
        # cell halfway to its neighbours. A boundary between lamps must not
        # silently truncate a long horizontal spine at the last centre.
        select_axis(centres,box,0)  # Validate box and calibration.
        points=sorted((float(p['xy'][0]),int(p['index'])) for p in centres)
        if len(points)<2:raise ValueError('insufficient_horizontal_calibration')
        cells=[]
        for n,(x,index) in enumerate(points):
            left=(points[n-1][0]+x)/2 if n else x-(points[1][0]-x)/2
            right=(x+points[n+1][0])/2 if n+1<len(points) else x+(x-points[n-1][0])/2
            if min(right,box[2])-max(left,box[0])>1e-6:cells.append(index)
        if not cells:raise ValueError('book_projection_outside_measured_leds')
        return {i:1.0 for i in cells},dict(method='book_width_cells',book_interval=[box[0],box[2]])
    quad=match.get('title_box')
    if not isinstance(quad,list) or len(quad)!=4 or any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in quad):
        raise ValueError('upright_title_axis_missing')
    midpoint=lambda a,b:((a[0]+b[0])/2,(a[1]+b[1])/2)
    # Opposite short edges bound the long text axis, independent of corner order.
    if math.dist(quad[0],quad[1])+math.dist(quad[2],quad[3]) <= math.dist(quad[1],quad[2])+math.dist(quad[3],quad[0]):
        a,b=midpoint(quad[0],quad[1]),midpoint(quad[2],quad[3])
    else:a,b=midpoint(quad[1],quad[2]),midpoint(quad[3],quad[0])
    if a[1]>b[1]:a,b=b,a
    direction=(b[0]-a[0],b[1]-a[1])
    if direction[1]<30 or abs(direction[0])>direction[1]*.7:
        raise ValueError('upright_title_axis_unreliable')
    points=sorted(centres,key=lambda p:p['xy'][0])
    if len(points)<2:raise ValueError('insufficient_horizontal_calibration')
    cross=lambda p,q:p[0]*q[1]-p[1]*q[0]
    hits=[]
    for left,right in zip(points,points[1:]):
        p=left['xy'];segment=(right['xy'][0]-p[0],right['xy'][1]-p[1])
        denominator=cross(direction,segment)
        if abs(denominator)<1e-8:continue
        offset=(p[0]-a[0],p[1]-a[1])
        t=cross(offset,segment)/denominator;u=cross(offset,direction)/denominator
        if t>=0 and -1e-8<=u<=1+1e-8:
            u=max(0.,min(1.,u));xy=[p[0]+u*segment[0],p[1]+u*segment[1]]
            hits.append((t,u,left,right,xy))
    if not hits:
        # A book centre can lie just beyond the first/last pixel while still
        # belonging to that pixel's half-spacing end cell. Never invent an LED.
        for endpoint,neighbour,side in ((points[0],points[1],-1),(points[-1],points[-2],1)):
            x,y=endpoint['xy'];t=(y-a[1])/direction[1]
            projected=a[0]+t*direction[0];distance=abs(projected-x)
            if t>=0 and (projected-x)*side>=0 and distance<=math.dist(endpoint['xy'],neighbour['xy'])/2:
                return {endpoint['index']:1.0},dict(method='nearest_measured_endpoint',title_axis=[a,b],
                    projected_endpoint_row=[projected,y],distance_to_measured_led=distance,
                    physical_weights={str(endpoint['index']+1):1.0})
        raise ValueError('book_projection_outside_measured_leds')
    _,u,left,right,xy=min(hits,key=lambda hit:hit[0])
    weights={left['index']:1-u,right['index']:u}
    weights={i:w for i,w in weights.items() if w>1e-6}
    return weights,dict(method='title_axis_intersection',title_axis=[a,b],rail_intersection=xy,
                        physical_weights={str(i+1):w for i,w in weights.items()})
