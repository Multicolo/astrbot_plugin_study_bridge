"""把 d8 产出的 classes.dex 塞进 aapt2 link 出来的 apk（纯标准库，无第三方依赖）。"""

import sys
import zipfile

src, dex, dst = sys.argv[1], sys.argv[2], sys.argv[3]
with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename == "classes.dex":
            continue
        zout.writestr(item, zin.read(item.filename))
    with open(dex, "rb") as handle:
        zout.writestr("classes.dex", handle.read())
print("wrote", dst)
