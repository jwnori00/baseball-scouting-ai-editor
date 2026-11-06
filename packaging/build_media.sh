#!/usr/bin/env bash
# Native Windows tools, exact source revisions, retained GPL corresponding source.
set -euo pipefail
root="$PWD"
assets="$root/vendor/portable"
prefix="$root/vendor/media"
mkdir -p "$prefix" "$assets/tools" "$assets/licenses/media" "$assets/corresponding-source/media" build/media
fetch_source() {
    local name="$1" remote="$2" revision="$3"
    local tree="$root/build/media/$name"
    if [[ ! -d "$tree/.git" ]]; then git init "$tree"; git -C "$tree" remote add origin "$remote"; fi
    test "$(git -C "$tree" remote get-url origin)" = "$remote"
    git -C "$tree" diff --exit-code
    git -C "$tree" diff --cached --exit-code
    git -C "$tree" fetch --depth 1 origin "$revision"
    git -C "$tree" checkout --detach FETCH_HEAD
    test "$(git -C "$tree" rev-parse HEAD)" = "$revision"
    git -C "$tree" archive --format=tar --prefix="$name/" HEAD | gzip -n > "$assets/corresponding-source/media/$name-$revision.tar.gz"
}
fetch_source x264 https://github.com/mirror/x264.git c24e06c2e184345ceb33eb20a15d1024d9fd3497
fetch_source ffmpeg https://github.com/FFmpeg/FFmpeg.git f46e514491172d15bd74b4abb1814cd2f05a763e
export PATH="/mingw64/bin:/usr/bin:$PATH"
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
jobs=$(nproc)
if (( jobs > 4 )); then jobs=4; fi
printf 'Native media build jobs: %s\n' "$jobs"
cd "$root/build/media/x264"
./configure --prefix="$prefix" --enable-static --disable-cli --disable-opencl --extra-ldflags=-static
make -j"$jobs"
make install
cp COPYING "$assets/licenses/media/x264-COPYING"
cd "$root/build/media/ffmpeg"
./configure --prefix="$prefix" --target-os=mingw32 --arch=x86_64 --cc=gcc --cxx=g++ \
    --disable-shared --enable-static --disable-autodetect --disable-doc --disable-debug \
    --disable-network --enable-gpl --enable-libx264 --pkg-config-flags=--static --extra-ldflags=-static \
    --disable-decoders --enable-decoder=h264,hevc,vp9,vp8,mpeg4,mpeg2video,mjpeg,ffv1,rawvideo,aac,aac_fixed,mp3,mp3float,pcm_u8,wrapped_avframe,pcm_s16le,pcm_s24le,pcm_f32le,flac,opus,vorbis,ac3,eac3,alac \
    --disable-demuxers --enable-demuxer=mov,matroska,mpegts,mpegps,avi,rawvideo,concat \
    --disable-encoders --enable-encoder=libx264,aac,ffv1,rawvideo,pcm_s16le,wrapped_avframe \
    --disable-muxers --enable-muxer=mp4,matroska,rawvideo,null \
    --disable-filters --enable-filter=fps,scale,showinfo,setsar,pad,select,setpts,testsrc2,sine,anullsrc,aresample,aformat,format,anull,null,transpose,hflip,vflip,crop,rotate \
    --disable-outdevs --disable-ffplay
make -j"$jobs"
make install
cp "$prefix/bin/ffmpeg.exe" "$prefix/bin/ffprobe.exe" "$assets/tools/"
cp COPYING.GPLv2 COPYING.GPLv3 LICENSE.md "$assets/licenses/media/"
cp ffbuild/config.log "$assets/corresponding-source/media/"
cp "$root/packaging/build_media.sh" "$assets/corresponding-source/media/"
gcc --version > "$assets/corresponding-source/media/compiler.txt"
"$assets/tools/ffmpeg.exe" -version > "$assets/corresponding-source/media/ffmpeg-version.txt"
# MSYS2's MINGW64 Tesseract is a native Windows executable, no MSYS shell needed.
cp /mingw64/bin/tesseract.exe "$assets/tools/"
while IFS= read -r dll; do cp "$dll" "$assets/tools/"; done < <(ldd /mingw64/bin/tesseract.exe | awk '/=> \/mingw64\// {print $3}')
mkdir -p "$assets/licenses/msys2"
cp -RL /mingw64/share/licenses/. "$assets/licenses/msys2/"
pacman -Q > "$assets/corresponding-source/media/msys2-package-versions.txt"

"$assets/tools/ffmpeg.exe" -v error -nostdin -f lavfi -i 'testsrc2=size=160x90:rate=10:duration=1' -f lavfi -i 'anullsrc=r=48000:cl=stereo' -t 1 -c:v libx264 -c:a aac -f mp4 -y "$root/build/media/native-smoke.mp4"
"$assets/tools/ffmpeg.exe" -v error -xerror -nostdin -i "$root/build/media/native-smoke.mp4" -f null -
