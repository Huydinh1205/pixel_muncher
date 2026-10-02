# Hướng dẫn chạy thử Pixel Muncher GUI trên Mac

Có 2 chế độ chạy thử trên Mac:

| Lệnh | Dữ liệu | Cắt tile | Phân loại |
|---|---|---|---|
| `bash run.sh --mock` | dữ liệu giả có sẵn | giả | giả |
| `bash run.sh --local` | **file .tif thật của bạn** | **thật (GDAL gdal2tiles)** | giả, tô màu theo độ xanh |

Pixel Muncher thật cần GPU NVIDIA + CUDA, nên chỉ chạy được trên máy GPU của công ty. Trên Mac, phân loại được thay bằng `mock/fake_inference.py`. Script này tô màu từng pixel theo chỉ số Excess Green, **không phải model**. Nó chỉ dùng để kiểm tra rằng toàn bộ luồng chạy đúng với ảnh thật: cắt tile, xếp hàng job, sắp xếp kết quả, mở bản đồ.

## Bước 1. Mở Terminal và vào folder

```bash
cd ~/đường/dẫn/tới/pixel_muncher
```

## Bước 2. Kiểm tra conda

```bash
conda --version
```

Nếu báo `command not found`, cài Miniforge (bản conda nhẹ, mặc định dùng conda-forge):

```bash
brew install miniforge
conda init zsh
```

Sau đó đóng Terminal, mở lại và làm lại Bước 1.

## Bước 3. Tạo môi trường có GDAL (chỉ làm 1 lần)

GDAL cài qua pip trên Mac hay lỗi, nên dùng conda-forge:

```bash
conda create -n pxm -c conda-forge python=3.11 gdal pillow numpy -y
conda activate pxm
pip install -r requirements.txt
```

Kiểm tra:

```bash
python -c "from osgeo_utils import gdal2tiles; from osgeo import gdal; print('GDAL', gdal.__version__)"
```

Thấy `GDAL 3.x.x` là được.

## Bước 4. Chạy demo trước (không cần file tif)

```bash
bash run.sh --mock
```

Mở trình duyệt vào **http://127.0.0.1:8080**, chọn `SiteA`, bấm **Add to queue**, rồi xem tab **Runs**. Bấm Ctrl+C trong Terminal để tắt.

## Bước 5. Thử với file .tif thật

Mỗi orthomosaic phải nằm trong một folder project riêng bên trong `local_data/`. Tên folder chính là tên project.

```bash
mkdir -p local_data/TestSite
```

**Cách A: ortho nhỏ (dưới khoảng 1 GB).** Tạo shortcut tới file, không cần copy:

```bash
ln -s "/đường/dẫn/tới/ortho.tif" local_data/TestSite/
```

**Cách B: ortho lớn.** Cắt một mẩu 5000×5000 pixel ở giữa ảnh để test cho nhanh. Ở zoom 23, ortho lớn có thể sinh ra hàng chục nghìn tile.

```bash
gdalinfo "/đường/dẫn/tới/ortho.tif" | grep "Size is"
# ví dụ ra: Size is 40000, 30000  ->  lấy mẩu ở giữa:
gdal_translate -srcwin 17500 12500 5000 5000 -co COMPRESS=DEFLATE \
  "/đường/dẫn/tới/ortho.tif" local_data/TestSite/TestSite_crop.tif
```

Sau đó chạy:

```bash
bash run.sh --local
```

Trong http://127.0.0.1:8080:

1. Chọn `TestSite / ...tif`. Công tắc **Make tiles** sẽ tự bật vì chưa có tile.
2. Chọn model. Model ở đây là file giả, chỉ có tên.
3. Nếu muốn, bật confidence rồi kéo slider. Kéo lên 0.95 sẽ thấy nhiều pixel bị bỏ trống hơn.
4. Bấm **Add to queue**, rồi sang tab **Runs** xem log và tiến độ.
5. Khi job xong, bấm **Open map**. Bản đồ hiện lớp phân loại chồng lên orthomosaic. Kéo slider độ mờ để so sánh hai lớp. Bản đồ này chạy offline.

Kết quả nằm ở `local_data/TestSite_Result/<ngày>_<model>_<confidence>/`, gồm:
- `23/`: các tile đã phân loại.
- `log.log`
- `run_manifest.json`
- `model_config/`

## Những gì nên thử

- Chạy lại nhưng để **Make tiles** tắt. Lần này phải nhanh hơn vì dùng lại tile có sẵn.
- Xếp 2 job liền nhau. Job thứ hai phải đợi job đầu xong mới chạy.
- Bấm **Cancel** khi một job đang chạy.
- Chạy `MOCK_FAIL=1 bash run.sh --local`. Job sẽ lỗi giữa chừng để bạn xem cách app báo lỗi.
- Tắt app bằng Ctrl+C khi đang có job chạy, rồi bật lại. Job đó phải hiện **Failed (Interrupted)**.

## Tạo icon app trên Mac

Chạy lệnh dưới 1 lần để tạo `Pixel Muncher.app` trong folder. Từ đó trở đi chỉ cần double-click, không phải mở Terminal:

```bash
bash launchers/macos/make_app.sh            # chế độ --local (file .tif của bạn)
bash launchers/macos/make_app.sh --mock     # hoặc chế độ demo
```

Khi bấm vào icon:
- Nếu app chưa chạy, nó tự khởi động bằng môi trường conda `pxm`.
- App mở trong cửa sổ riêng như một app bình thường. Nếu máy có Chrome, Edge hoặc Brave thì dùng chế độ app window của trình duyệt đó, không có thì mở bằng Safari.
- Muốn ghim lên Dock: kéo `Pixel Muncher.app` từ Finder thả vào Dock.

Nút nguồn ở góc phải trên cùng dùng để tắt app. Đóng cửa sổ thì app vẫn chạy ngầm.

Giữ file `.app` trong folder này. Nếu dời folder đi chỗ khác, chạy lại `make_app.sh`. Lần đầu nếu macOS chặn không cho mở, chuột phải vào app, chọn *Open*, rồi bấm *Open* lần nữa. Nếu app không khởi động được, lý do nằm trong `local_state/app.log`.

## Lỗi hay gặp

| Lỗi | Cách sửa |
|---|---|
| `Tiling tool: ... cannot import osgeo_utils.gdal2tiles` | Chưa chạy `conda activate pxm` trước `bash run.sh` |
| `Address already in use` | Port 8080 đang bị app khác dùng. Sửa `port:` trong `config.local.yaml` |
| Không thấy file .tif trong danh sách | File phải nằm trong `local_data/<Project>/`, không đặt thẳng trong `local_data/`. Bấm nút ↻ để quét lại |
| Bản đồ trắng | Ortho có thể không có hệ tọa độ (CRS). Kiểm tra bằng `gdalinfo file.tif` |

Chạy test tự động: `python -m pytest -q`
