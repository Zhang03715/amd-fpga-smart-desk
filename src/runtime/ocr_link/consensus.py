"""Bounded fresh-frame book confirmation; text agreement alone cannot move a vote."""
import math
import re


def title_key(text):
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]','',text.lower())


_EDITION = re.compile(
    r'(?:[（(【\[]\s*)?(?:第?\s*[0-9零〇一二三四五六七八九十百两]+\s*年?\s*版'
    r'|(?:[0-9]{4}\s*年?\s*)?(?:修订|增订|修正|更新|再|新)版)'
    r'\s*[）)】\]]?\s*$')


def book_title_key(text):
    """Ignore explicit trailing edition metadata, preserving the printed text."""
    original=text
    text=text.strip().strip('《》“”\"\'').rstrip('。．.,，;；').strip()
    while True:
        match=_EDITION.search(text)
        if match is None:break
        base=text[:match.start()].rstrip()
        if len(title_key(base))<2:break
        text=base
    return title_key(text or original)


def edition_candidates(matches):
    """Collapse edition spellings of one physical title, never two locations."""
    groups=[]
    for match in sorted(matches,key=lambda m:m['ocr_confidence'],reverse=True):
        b=title_bounds(match)
        if len(b)!=4 or not all(math.isfinite(v) for v in b) or b[0]>=b[2] or b[1]>=b[3]:
            raise ValueError('invalid evidence bounds')
        compatible=[g for g in groups if all(title_key(m['text'])!=title_key(match['text'])
                    and (overlap(title_bounds(m),b)>=.5 or
                         (book_title_key(m['text'])==book_title_key(match['text'])
                          and m.get('orientation')==match.get('orientation')
                          and overlap(m['book_box'],match['book_box'])>=.5
                          and contained_title(title_bounds(m),b)>=.8)) for m in g)]
        if len(compatible)==1:compatible[0].append(match)
        else:groups.append([match])
    return [group[0] for group in groups]


def repeated_prefix_query(text):
    """One conservative ASR stutter interpretation, never an OCR correction."""
    key=title_key(text)
    for size in range(2,min(8,(len(key)-2)//2)+1):
        prefix=key[:size]
        if (all('\u4e00'<=c<='\u9fff' for c in prefix) and key[size:size*2]==prefix
                and len(key[size:])>=4):return key[size:]
    return None


def title_bounds(match):
    p=match.get('title_box')
    if p:
        return [min(q[0] for q in p),min(q[1] for q in p),max(q[0] for q in p),max(q[1] for q in p)]
    return match['book_box']


def overlap(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def contained_title(a,b):
    area=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1])))



def glyph_conflict_resolved(decision,target):
    """A selected reflow with two high-confidence agreeing layouts resolves its old flag."""
    query=decision.get('query_crop_review',{})
    if query.get('selected') and query.get('method')=='native_pixels_query_crop_two_recognizers':
        supported={r.get('model') for r in query.get('rows',[]) if book_title_key(r.get('text',''))==target and r.get('confidence',0)>=.95}
        if {'primary','secondary'}<=supported:return True
    glyph=decision.get('upright_glyph_review',{})
    if not glyph.get('selected') or book_title_key(glyph.get('text',''))!=target or glyph.get('confidence',0)<.95:
        return False
    return any(attempt.get('selected') and book_title_key(attempt.get('text',''))==target
               and book_title_key(attempt.get('corroborating_text',''))==target
               and attempt.get('confidence',0)>=.95 and attempt.get('corroborating_confidence',0)>=.95
               for attempt in glyph.get('attempts',[]))


class BookFrameConsensus:
    def __init__(self,target,allow_fast_path=True,max_frames=3,single_frame=False):
        self.target=book_title_key(target)
        if not self.target:raise ValueError('empty target')
        self.frames=[];self.votes=[];self.device=None;self.last_sequence=-1;self.last_time=-1
        self.unstable=False;self.confirmed=False;self.fast_path=False
        self.single_frame=single_frame
        self.allow_fast_path=allow_fast_path
        if type(max_frames) is not int or not ((single_frame and max_frames==1) or (not single_frame and 3<=max_frames<=5)):raise ValueError('invalid confirmation frame limit')
        self.max_frames=max_frames

    def observe(self,result,info):
        if self.confirmed or len(self.frames)>=self.max_frames:raise ValueError('confirmation already finished')
        seq,stamp=info['sequence'],info['captured_monotonic']
        if (type(seq) is not int or not math.isfinite(stamp) or seq<=self.last_sequence
                or stamp<=self.last_time or (self.device is not None and info['device']!=self.device)):
            raise ValueError('duplicate, reordered or different-camera frame')
        self.device=info['device'];self.last_sequence=seq;self.last_time=stamp
        raw_candidates=[m for m in result.get('matches',[]) if book_title_key(m['text'])==self.target
                    and math.isfinite(m['ocr_confidence']) and m['ocr_confidence']>=.90]
        candidates=edition_candidates(raw_candidates)
        record=dict(sequence=seq,captured_monotonic=stamp,matching_candidates=len(candidates),
                    matching_text_variants=len(raw_candidates))
        self.frames.append(record)
        if len(candidates)!=1:
            record['reason']='no_matching_title' if not candidates else 'multiple_title_locations'
            self.unstable=True;return None
        match=candidates[0];b=title_bounds(match)
        if len(b)!=4 or not all(math.isfinite(v) for v in b) or b[0]>=b[2] or b[1]>=b[3]:raise ValueError('invalid evidence bounds')
        def unresolved(decision):
            native=decision.get('native_review',{})
            if not (native.get('conflict',False) or (decision.get('recognition_conflict',False) and not glyph_conflict_resolved(decision,self.target))):return False
            # A same-location rotated pass with a second recognizer can settle
            # an old expanded-crop conflict; unrelated title regions cannot.
            if native.get('selected') and book_title_key(native.get('text',''))==self.target and native.get('confidence',0)>=.97:
                points=decision.get('points')
                if points:
                    bounds=title_bounds({'title_box':points})
                    for other in result.get('decisions',[]):
                        review=other.get('rotated_review',{})
                        if (other is not decision and other.get('points') and not review.get('conflict',False)
                            and book_title_key(other.get('v4_text',''))==self.target and other.get('v4_confidence',0)>=.97
                            and book_title_key(review.get('secondary_text',''))==self.target and review.get('secondary_confidence',0)>=.97
                            and overlap(bounds,title_bounds({'title_box':other['points']}))>=.5):return False
            return True
        # Final selection owns rejection. Discarded intermediate crops cannot
        # veto the selected transcript; their positive corroboration remains usable.
        relevant_decisions=[d for d in result.get('decisions',[])
            if d.get('accepted') is not False and book_title_key(d.get('v4_text',''))==self.target
            and (not d.get('points') or overlap(title_bounds({'title_box':d['points']}),b)>=.3
                 or contained_title(title_bounds({'title_box':d['points']}),b)>=.8)]
        conflict=any(unresolved(d) for d in relevant_decisions)
        record['discarded_decisions_ignored']=sum(d.get('accepted') is False for d in result.get('decisions',[]))
        corroborated=any(
            d.get('points') and book_title_key(d.get('v4_text',''))==self.target and d.get('v4_confidence',0)>=.97
            and book_title_key(d.get('rotated_review',{}).get('secondary_text',''))==self.target
            and d.get('rotated_review',{}).get('secondary_confidence',0)>=.97
            and not d.get('rotated_review',{}).get('conflict',False)
            and overlap(title_bounds({'title_box':d['points']}),b)>=.5
            for d in result.get('decisions',[]))
        spatial_conflict=any(book_title_key(m.get('text',''))!=self.target
                             and len(book_title_key(m.get('text','')))>=max(4,len(self.target)*.7)
                             and m.get('ocr_confidence',0)>=.90 and not (corroborated and m.get('ocr_confidence',0)<.97)
                             and overlap(title_bounds(m),b)>=.5
                             for m in result.get('matches',[]))
        conflict=conflict or spatial_conflict
        self.votes.append(dict(match=match,bounds=b,sequence=seq))
        votes=sum(overlap(v['bounds'],b)>=.5 for v in self.votes)
        record.update(confidence=match['ocr_confidence'],conflicting_native_review=conflict,
                      overlapping_transcription_conflict=spatial_conflict,consistent_votes=votes)
        record['reason']='transcription_conflict' if conflict else 'title_confirmed'
        if self.single_frame:
            if conflict:return None
            self.confirmed=True;self.fast_path=True;return match
        if self.allow_fast_path and len(self.frames)==1 and match['ocr_confidence']>=.95 and not conflict:
            self.confirmed=True;self.fast_path=True;return match
        self.unstable=True
        if votes>=2:
            self.confirmed=True;return match
        return None

    def info(self):
        return dict(confirmed=self.confirmed,fast_path=self.fast_path,frames=self.frames,single_frame=self.single_frame,
                    title_matching='main_title_ignore_edition',normalized_target=self.target,
                    max_frames=self.max_frames,required_votes=1 if self.single_frame or self.fast_path else 2)
