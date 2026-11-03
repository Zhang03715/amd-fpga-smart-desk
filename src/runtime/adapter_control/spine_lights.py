"""Measured camera-to-LED mapping. No default image-width approximation."""
import math


class SpineLightMapper:
    def __init__(self, *, calibration_id, camera_id, image_size, axis, positions,
                 shelf_range, physical_count=30, active_count=15, hysteresis=2.0,pixel_indices=None):
        if axis not in ('x','y') or not calibration_id or not camera_id:
            raise ValueError('invalid_light_calibration')
        if (type(physical_count) is not int or type(active_count) is not int
                or not 1<=active_count<=physical_count<=256 or len(positions)!=active_count):
            raise ValueError('invalid_light_counts')
        if (len(image_size)!=2 or any(type(v) is not int or v<=0 for v in image_size)
                or len(shelf_range)!=2):raise ValueError('invalid_calibration_geometry')
        extent=image_size[0 if axis=='x' else 1]
        values=list(positions)+list(shelf_range)+[hysteresis]
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
            raise ValueError('invalid_calibration_number')
        if not 0<=shelf_range[0]<shelf_range[1]<=extent or hysteresis<0:
            raise ValueError('invalid_shelf_range')
        differences=[b-a for a,b in zip(positions,positions[1:])]
        if not (all(x>0 for x in differences) or all(x<0 for x in differences)):
            raise ValueError('led_positions_must_be_monotonic')
        if any(not shelf_range[0]<=p<=shelf_range[1] for p in positions):
            raise ValueError('led_position_outside_shelf')
        self.calibration_id,self.camera_id=calibration_id,str(camera_id)
        self.image_size,self.axis=tuple(image_size),axis
        self.positions,self.shelf_range=tuple(positions),tuple(shelf_range)
        self.physical_count,self.active_count=physical_count,active_count
        self.pixel_indices=tuple(range(active_count)) if pixel_indices is None else tuple(pixel_indices)
        if (len(self.pixel_indices)!=active_count or len(set(self.pixel_indices))!=active_count
                or any(type(i) is not int or not 0<=i<physical_count for i in self.pixel_indices)):
            raise ValueError('invalid_calibrated_pixel_indices')
        self.hysteresis=hysteresis
        self.previous=None

    def plan(self, box, *, camera_id, image_size, target_id):
        if str(camera_id)!=self.camera_id or tuple(image_size)!=self.image_size:
            raise ValueError('light_calibration_camera_mismatch')
        if (len(box)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in box)
                or not 0<=box[0]<box[2]<=image_size[0]
                or not 0<=box[1]<box[3]<=image_size[1]):raise ValueError('invalid_spine_box')
        lo,hi=(box[0],box[2]) if self.axis=='x' else (box[1],box[3])
        if lo<self.shelf_range[0] or hi>self.shelf_range[1]:
            raise ValueError('spine_outside_calibrated_shelf')
        pairs=sorted(zip(self.positions,self.pixel_indices))
        indices=[i for p,i in pairs if lo<=p<=hi]
        if not indices:
            before=[(p,i) for p,i in pairs if p<lo]
            after=[(p,i) for p,i in pairs if p>hi]
            indices=([before[-1][1]] if before else [])+([after[0][1]] if after else [])
        if self.previous:
            target,old_span,old_indices=self.previous
            if target==target_id and max(abs(lo-old_span[0]),abs(hi-old_span[1]))<=self.hysteresis:
                return list(old_indices)
        indices=sorted(indices)
        self.previous=(target_id,(lo,hi),tuple(indices))
        return indices

    def pixels(self, indices, rgb=(0,255,0)):
        if any(type(i) is not int or i not in self.pixel_indices for i in indices):
            raise ValueError('inactive_led_index')
        return [rgb if i in indices else (0,0,0) for i in range(self.physical_count)]

    def info(self):
        return dict(configured=True,calibration_id=self.calibration_id,camera_id=self.camera_id,
                    image_size=list(self.image_size),axis=self.axis,physical_count=self.physical_count,
                    active_count=self.active_count,pixel_indices=list(self.pixel_indices),channel=1,index_base=0)
