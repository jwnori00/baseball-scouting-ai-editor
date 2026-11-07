# Synthetic AV1 decoder fixtures

These 1.2-second AV1/AAC files contain only FFmpeg `testsrc2` and a generated
440 Hz sine wave. No uploaded broadcast or personal media is included.

Both use `testsrc2=s=96x54:r=5:d=1.2`, `sine=frequency=440:sample_rate=48000:duration=1.2`,
`-c:v libaom-av1 -cpu-used 8 -crf 35 -b:v 0 -threads 2 -c:a aac`.
Pixel formats are `yuv420p` (8-bit) and `yuv420p10le` (10-bit).
The encoded fixtures are committed so the Windows runtime needs only an AV1
decoder, never an AV1 encoder. These test codec compatibility, not baseball accuracy or HDR color preservation.
