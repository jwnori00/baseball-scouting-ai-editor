"""Conservative, bounded-memory black-border detection for approved segments."""
import math
import numpy as np
from bsae.ingest.media import frames


def detect_crop(path, start, end, video, stop=None):
    # Union every decoded sample: a full-screen cut prevents cropping the segment.
    # Overscan protects dim edges, captions and resampling boundaries.
    width, height = int(video['width']), int(video['height'])
    sw = min(640, width)
    sh = max(2, round(height * sw / width))
    left, top, right, bottom = sw, sh, 0, 0
    count = 0
    from fractions import Fraction
    rate = video.get('avg_frame_rate', '30/1')
    fps = float(Fraction(rate)) if rate not in ('0/0', '0/1') else 30
    for _, image in frames(path, fps=max(30, fps), width=sw, height=sh, start=start, end=end):
        if stop is not None and stop.is_set():
            raise RuntimeError('출력 취소')
        y, x = np.nonzero(np.max(image, axis=2) > 16)
        if not len(x):
            continue
        count += 1
        left, top = min(left, int(x.min())), min(top, int(y.min()))
        right, bottom = max(right, int(x.max()) + 1), max(bottom, int(y.max()) + 1)
        if left < 4 and top < 4 and right > sw-4 and bottom > sh-4:
            return None
    if not count:
        return None
    x = max(0, math.floor((left-3)*width/sw/2)*2)
    y = max(0, math.floor((top-3)*height/sh/2)*2)
    r = min(width//2*2, math.ceil((right+3)*width/sw/2)*2)
    b = min(height//2*2, math.ceil((bottom+3)*height/sh/2)*2)
    # Avoid zooming for negligible borders or tiny/unreliable content.
    if (r-x)*(b-y) > width*height*.90 or r-x < width*.10 or b-y < height*.10:
        return None
    return (r-x, b-y, x, y)


def crop_filter(crop, video):
    """Map sampled fractions onto FFmpeg's decoded (autorotated) geometry.

    ffprobe width/height describe coded storage, not necessarily filter input.
    Relative coordinates also remain valid when the decoder changes resolution.
    """
    if crop is None:
        return ''
    w,h,x,y=crop
    width,height=int(video['width']),int(video['height'])
    if min(w,h)<=0 or min(x,y)<0 or x+w>width or y+h>height:
        raise ValueError('자동 여백 영역이 분석 화면 범위를 벗어났습니다')
    return (f"crop=w='max(2,trunc(iw*{w}/{width}/2)*2)'"
            f":h='max(2,trunc(ih*{h}/{height}/2)*2)'"
            f":x='min(iw-ow,trunc(iw*{x}/{width}/2)*2)'"
            f":y='min(ih-oh,trunc(ih*{y}/{height}/2)*2)',")
