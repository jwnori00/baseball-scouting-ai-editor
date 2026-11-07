"""Versioned output preferences independent of scene recognition."""
import math


def default_output_settings():
    return dict(aspect='source',custom_width=16.,custom_height=9.,resolution=720,placement='fit',auto_frame=False)


def legacy_output_settings():
    return dict(default_output_settings(),aspect='16:9',auto_frame=True)


def validate_output_settings(settings):
    result=default_output_settings();result.update(settings)
    if result['aspect'] not in ('source','16:9','4:3','9:16','1:1','custom'):raise ValueError('출력 화면비율 오류')
    if result['resolution'] not in (720,1080) or result['placement']!='fit' or not isinstance(result['auto_frame'],bool):raise ValueError('출력 해상도/배치 오류')
    for key in ('custom_width','custom_height'):
        value=result[key]
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('사용자 화면비율은 양의 유한한 값이어야 합니다')
    return result
