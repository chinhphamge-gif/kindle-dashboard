import sys
from PIL import Image, ImageOps, ImageFilter
import numpy as np
from scipy import ndimage
U="/mnt/user-data/uploads/"
M={"e1090ebd":"hero","f6c3c80b":"panic","5f24667d":"thumbs","d2a862c9":"astronaut","3ddc44db":"confused",
   "bd5fe3ce":"sleep","33ae2e88":"stars","40fe5ee2":"pokeball","598039e8":"blanket","4e765759":"pharaoh",
   "c65d09af":"glasses","24e16f43":"dizzy"}
out=sys.argv[1]
for k,n in M.items():
    im=Image.open(f"{U}{k}-image.png").convert("RGBA")
    a=np.array(im)[:,:,3]
    lab,cnt=ndimage.label(a>40)
    sizes=ndimage.sum(np.ones_like(a),lab,range(1,cnt+1))
    big=max(sizes)
    keep=np.isin(lab,[i+1 for i,s in enumerate(sizes) if s>=0.004*big])
    # bỏ các mảnh nhỏ dạng chữ/vạch nằm sát đáy (dải dưới 6% chiều cao, cách xa thân chính)
    main=lab==(int(np.argmax(sizes))+1)
    ys=np.where(main.any(1))[0]; bottom=ys.max()
    for i,s in enumerate(sizes):
        comp=lab==(i+1)
        cy=np.where(comp.any(1))[0]
        if cy.min()>bottom-2 or (s<0.02*big and cy.min()>a.shape[0]*0.9): keep&=~comp
    arr=np.array(im); arr[:,:,3]=np.where(keep,arr[:,:,3],0)
    im=Image.fromarray(arr)
    im=im.crop(im.getbbox())
    # thang xám cho e-ink: phủ lên nền trắng, tăng tương phản, giữ kênh alpha
    rgb=Image.new("RGB",im.size,"white"); rgb.paste(im,mask=im.split()[3])
    g=ImageOps.grayscale(rgb)
    g=g.point(lambda v: max(0,min(255,int((v-150)*1.7+150)) if v>150 else int(v*0.75)))   # đậm phần vàng thành xám vừa
    g=g.filter(ImageFilter.UnsharpMask(1.0,80,2))
    la=Image.merge("LA",(g,im.split()[3]))
    la.thumbnail((300,300),Image.LANCZOS); la.save(f"{out}/{n}.png",optimize=True)
    print(n,la.size)
