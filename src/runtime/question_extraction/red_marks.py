"""Red X candidates are selection hints, never a correctness judgement."""
def detect_red_crosses(image):
 import cv2,numpy as np
 rgb=np.array(image.convert('RGB'));hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
 mask=(((hsv[:,:,0]<12)|(hsv[:,:,0]>168))&(hsv[:,:,1]>110)&(hsv[:,:,2]>80)).astype('uint8')
 n,labels,stats,centres=cv2.connectedComponentsWithStats(mask)
 result=[]
 for i in range(1,n):
  x,y,w,h,area=map(int,stats[i])
  if area<35 or min(w,h)<10 or not .45<=w/h<=2.2:continue
  yy,xx=np.where(labels[y:y+h,x:x+w]==i);xx=xx/max(w-1,1);yy=yy/max(h-1,1)
  a=np.abs(xx-yy)<.18;b=np.abs(xx+yy-1)<.18
  if a.mean()<.28 or b.mean()<.28 or (a|b).mean()<.72:continue
  result.append({'box':[x,y,x+w,y+h],'center':[float(centres[i][0]),float(centres[i][1])],'kind':'red_cross_candidate','requires_confirmation':True})
 return result

def associate_marks(questions,marks):
 out=[dict(q,marked=False,mark_indices=[]) for q in questions];unassigned=[]
 for i,mark in enumerate(marks):
  x,y=mark['center'];hits=[q for q in out if q['box'][0]<=x<q['box'][2] and q['box'][1]<=y<q['box'][3]]
  if not hits:
   # A red X can obscure the first question number. Preserve that region as
   # an explicitly unnumbered candidate, never attach it to the next question.
   below=[q for q in out if q['box'][0]<=x<q['box'][2] and q['box'][1]>y]
   if below:
    next_q=min(below,key=lambda q:q['box'][1]);mx,my,mr,mb=mark['box'];height=mb-my
    if next_q['box'][1]-mb<=3*height and next_q.get('number')==2 and not any(q['column']==next_q['column'] and q['box'][1]<y for q in out):
     out.append(dict(number='待确认',column=next_q['column'],box=[next_q['box'][0],max(0,int(my-height*.5)),next_q['box'][2],next_q['box'][1]],anchor_text='',review_required=True,reasons=['red_cross_without_first_question_anchor','confirm_complete_question_and_number'],marked=True,mark_indices=[i]));continue
  if len(hits)!=1:unassigned.append(i);continue
  hits[0]['marked']=True;hits[0]['mark_indices'].append(i)
 return {'questions':out,'red_marks':marks,'unassigned_mark_indices':unassigned,'review_required':True}
