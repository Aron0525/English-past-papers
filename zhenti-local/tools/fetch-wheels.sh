#!/bin/bash
# 从阿里云 PyPI 镜像抓 wheel，curl 断点续传 + 重试，绕开 pip 的整包下载
export PATH="/usr/bin:/bin:$PATH"
MIRROR="https://mirrors.aliyun.com/pypi"
OUT="E:/workbuddy/仓库/rea/bv/wheels"
mkdir -p "$OUT"

pick() {
  # $1 = 包名（simple 索引里的规范化名），$2 = 文件名匹配正则
  local pkg="$1" pat="$2"
  curl -s --noproxy '*' --max-time 60 "$MIRROR/simple/$pkg/" \
    | grep -oE 'href="[^"]+"' | sed 's/^href="//; s/"$//; s/#.*$//' \
    | grep -iE "$pat" | tail -1
}

pull() {
  local pkg="$1" pat="$2"
  local rel
  rel=$(pick "$pkg" "$pat")
  if [ -z "$rel" ]; then echo "MISS  $pkg"; return 1; fi
  local url="$MIRROR/${rel#../../}"
  local file="$OUT/$(basename "$rel")"
  if [ -f "$file" ]; then
    local want got
    want=$(curl -sI --noproxy '*' --max-time 40 "$url" | grep -i content-length | tr -dc '0-9')
    got=$(stat -c%s "$file")
    if [ -n "$want" ] && [ "$got" = "$want" ]; then echo "OK    $(basename "$file") ($got)"; return 0; fi
  fi
  curl -sL --noproxy '*' -C - --max-time 300 "$url" -o "$file" -w "  $pkg http=%{http_code} got=%{size_download}\n"
  local want got
  want=$(curl -sI --noproxy '*' --max-time 40 "$url" | grep -i content-length | tr -dc '0-9')
  got=$(stat -c%s "$file" 2>/dev/null || echo 0)
  if [ -n "$want" ] && [ "$got" = "$want" ]; then echo "DONE  $(basename "$file") ($got)"; else echo "PART  $pkg $got/$want"; fi
}

for i in 1 2 3 4; do
  pull numpy           'numpy-[0-9.]+-cp313-cp313-win_amd64\.whl$'
  pull onnxruntime     'onnxruntime-1\.[0-9.]+-cp313-cp313-win_amd64\.whl$'
  pull opencv-python-headless 'opencv_python_headless-[0-9.]+-cp37-abi3-win_amd64\.whl$'
  pull pyclipper       'pyclipper-[0-9.]+-cp313-cp313-win_amd64\.whl$'
  pull shapely         'shapely-[0-9.]+-cp313-cp313-win_amd64\.whl$'
  pull PyYAML          'PyYAML-[0-9.]+-cp313-cp313-win_amd64\.whl$'
  pull six             'six-[0-9.]+-py2\.py3-none-any\.whl$'
  pull rapidocr_onnxruntime 'rapidocr_onnxruntime-[0-9.]+-py3-none-any\.whl$'
  echo "---- 第 $i 轮结束 ----"
  ls "$OUT" | wc -l
done
