"""Displayed geometry, including non-square pixels and phone rotation."""
from fractions import Fraction
import math
from bsae.core.output_settings import validate_output_settings


def display_aspect(video):
    width,height=int(video['width']),int(video['height'])
    if min(width,height)<=0:raise ValueError('원본 화면 크기 오류')
    value=video.get('sample_aspect_ratio','1:1')
    sar=Fraction(value.replace(':','/')) if value not in (None,'N/A','0:1','0/1') else Fraction(1)
    if sar<=0:raise ValueError('원본 픽셀 종횡비 오류')
    angle=next((float(d['rotation']) for d in video.get('side_data_list',[]) if 'rotation' in d),float(video.get('tags',{}).get('rotate',0)))
    if not math.isfinite(angle) or abs(angle/90-round(angle/90))>.001:raise ValueError('90도 단위가 아닌 회전 영상은 원본 표시 비율 검증이 필요합니다')
    ratio=Fraction(width,height)*sar
    return 1/ratio if round(angle/90)%2 else ratio


def output_dimensions(video,settings):
    settings=validate_output_settings(settings);mode=settings['aspect']
    ratio=display_aspect(video) if mode=='source' else Fraction(str(settings['custom_width']))/Fraction(str(settings['custom_height'])) if mode=='custom' else Fraction(mode.replace(':','/'))
    short=settings['resolution'];r=float(ratio)
    w,h=(short*r,short) if r>=1 else (short,short/r)
    factor=min(1,3840/max(w,h));w,h=w*factor,h*factor
    width,height=max(2,round(w/2)*2),max(2,round(h/2)*2)
    if min(width,height)<64:raise ValueError('화면비율이 지나치게 좁습니다. 출력 짧은 변은 최소 64픽셀입니다')
    return width,height
