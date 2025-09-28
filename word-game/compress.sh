#!/bin/bash
# 批次縮小圖片尺寸為 1/2，但寬或高若會小於 512 就不縮
# 用法: ./half_size_min512.sh /path/to/images

INPUT_DIR="${1:-.}"   # 預設當前目錄

for img in "$INPUT_DIR"/*.{jpg,jpeg,png,JPG,JPEG,PNG}; do
    [ -e "$img" ] || continue  # 沒檔案就跳過

    # 取得原始尺寸 (需要 ImageMagick 的 identify)
    dimensions=$(identify -format "%w %h" "$img")
    width=$(echo $dimensions | awk '{print $1}')
    height=$(echo $dimensions | awk '{print $2}')

    # 計算縮小一半後的尺寸
    new_width=$((width / 2))
    new_height=$((height / 2))

    # 檢查是否小於 512
    if [ $new_width -lt 512 ] || [ $new_height -lt 512 ]; then
        echo "⚠️ 跳過 (縮小後會小於 512)：$img"
        continue
    fi

    ext="${img##*.}"
    case "$ext" in
        jpg|jpeg|JPG|JPEG)
            mogrify -resize 50% -quality 85 -strip "$img"
            ;;
        png|PNG)
            mogrify -resize 50% -strip "$img"
            optipng -o7 "$img" >/dev/null 2>&1
            ;;
    esac
    echo "✅ 已縮小一半並壓縮: $img"
done

