"""Conservative numbered-question candidates; review is always required."""
import re,math
NUMBER=re.compile(r'^\s*([1-9]\d?)\s*[.．、]\s*\S')
def group_questions(regions,size,layout=()):
 w,h=size;anchors=[]
 for row in regions:
  m=NUMBER.match(row['text'])
  if not m or row.get('score',0)<.65:continue
  pts=row['box'];x=min(p[0] for p in pts);y=min(p[1] for p in pts)
  if not 0<=x<w or not 0<=y<h:continue
  anchors.append({'number':int(m[1]),'x':x,'y':y,'text':row['text']})
 anchors.sort(key=lambda a:a['x']);columns=[]
 for a in anchors:
  if not columns or a['x']-columns[-1][0]['x']>w*.22:columns.append([])
  columns[-1].append(a)
 if len(columns)>2:return {'questions':[],'review_required':True,'reason':'ambiguous_columns'}
 questions=[];centres=[sum(a['x'] for a in c)/len(c) for c in columns]
 boundaries=[0]+[(centres[i]+centres[i+1])/2 for i in range(len(centres)-1)]+[w]
 # Use the next column start minus a margin, not midpoint between question-number starts.
 if len(columns)==2:boundaries[1]=max(0,min(w,centres[1]-w*.025))
 for ci,column in enumerate(columns):
  column.sort(key=lambda a:a['y'])
  for i,a in enumerate(column):
   left=int(boundaries[ci]);right=int(boundaries[ci+1]);top=max(0,int(a['y']-h*.006));bottom=int(column[i+1]['y']-h*.006) if i+1<len(column) else int(h*.97)
   if bottom-top<h*.025:continue
   reasons=['confirm_complete_question_and_select_wrong_item']
   if sum(x['number']==a['number'] for x in anchors)>1:reasons.append('duplicate_question_number')
   for block in layout:
    b=block.get('coordinate',block.get('bbox',[]))
    if len(b)!=4:continue
    if b[0]<right and b[2]>left and b[1]<bottom and b[3]>top:
     if b[0]<left-5 or b[2]>right+5 or b[1]<top-10 or b[3]>bottom+10:reasons.append('layout_crosses_candidate_boundary');break
   questions.append({'number':a['number'],'column':ci,'box':[left,top,right,bottom],'anchor_text':a['text'],'review_required':True,'reasons':reasons})
 return {'questions':questions,'review_required':True,'reason':'candidate_regions_only' if questions else 'no_reliable_numbered_question_anchors'}
