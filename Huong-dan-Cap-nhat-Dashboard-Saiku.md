# Hướng dẫn cập nhật Dashboard Saiku

Khi bạn sửa / thêm dashboard hoặc chart trên **Saiku UI**, thay đổi đó chỉ nằm
trong **volume của container** (`saiku_data`). Nó **chưa** ở trong git.

`seed-entrypoint.sh` hiện chạy theo cơ chế **force-overwrite**: mỗi lần container
khởi động (mọi lần deploy), Saiku lấy lại bản dashboard trong `saiku/dashboards/`
của **git** và ghi đè lên volume.

> ⚠️ **Hệ quả:** nếu bạn sửa trên UI mà **không đẩy vào git**, thì lần deploy
> tiếp theo sẽ **ghi đè mất** thay đổi của bạn. Muốn giữ, phải export bản sửa
> vào git (git là "nguồn chân lý").

Đường dẫn dashboard trong container:
`/app/saiku-home/repository/data/unknown/homes/admin/`

---

## A. Sửa trên Saiku LOCAL (máy có git repo)

```bash
cd <đường-dẫn-repo>   # vd: ~/Master_Program/Advanced_BI/Final_Project_BI/advanced-bi

# 1) Export dashboard từ container ra repo
docker cp saiku:/app/saiku-home/repository/data/unknown/homes/admin/. ./saiku/dashboards/

# 2) Xem thay đổi (dọn file nháp nếu có: untitled-*, *-copy)
git status saiku/dashboards/

# 3) Commit + push
git add saiku/dashboards/
git commit -m "update dashboards"
git push
```

## B. Sửa trên Saiku VPS (server chung — 152.42.163.132)

Chạy **từ máy local** (nơi có git repo):

```bash
# 1) Kéo dashboard từ container trên VPS về repo local
ssh <user>@152.42.163.132 "docker cp saiku:/app/saiku-home/repository/data/unknown/homes/admin/. /tmp/saiku_dash"
rsync -az <user>@152.42.163.132:/tmp/saiku_dash/ ./saiku/dashboards/

# 2) Commit + push
git add saiku/dashboards/
git commit -m "update dashboards"
git push
```

---

## Lưu ý quan trọng

1. **Làm TRƯỚC khi deploy.** Nếu deploy chạy trước khi bạn export → bản sửa
   trên UI bị git ghi đè (mất).
2. **Dọn file nháp** (`untitled-dashboard`, `*-copy`, …) trong UI trước khi
   export, kẻo commit rác lên git.
3. `docker cp` chỉ **thêm / ghi đè**, **không xóa**. Nếu bạn **xóa** một
   dashboard trên UI, nhớ `git rm` file tương ứng trong `saiku/dashboards/`
   một cách thủ công.
4. Để bản git tới được VPS: cần một lần **deploy**, hoặc chạy tay trên VPS:
   ```bash
   cd /opt/bi_dw
   docker compose -f docker-compose.vps3.yml up -d --build saiku
   ```

---

## Kiểm tra nhanh (tùy chọn)

Liệt kê cube / xác nhận Saiku đang phục vụ đúng nội dung:

```bash
# đăng nhập REST rồi liệt kê cube
curl -s -c /tmp/ck -o /dev/null -X POST http://<host>:8080/rest/saiku/session -d "username=admin&password=admin"
curl -s -b /tmp/ck http://<host>:8080/rest/saiku/api/discover | tr ',' '\n' | grep -i '"name"'
```
