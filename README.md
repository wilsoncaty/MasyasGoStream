# Masyas Go Stream

Studio streaming YouTube berbasis Streamlit dengan tema putih dan merah.

- Playlist hingga 5 video, atau satu video berulang dengan playlist MP3.
- Sumber video dari perangkat, URL langsung, atau Google Drive.
- Pilihan mode Shorts, jumlah pengulangan, dan durasi siaran.
- Monitoring proses siaran, RAM/CPU aplikasi, storage file, dan trafik jaringan runtime.

## Deploy ke Streamlit Community Cloud

Di [Streamlit Community Cloud](https://share.streamlit.io), pilih **Create app** dan isi:

| Pengaturan | Nilai |
| --- | --- |
| Repository | `wilsoncaty/MasyasGoStream` |
| Branch | `main` |
| Main file path | `masyasgostream.py` |
| Python version (Advanced settings) | `3.11` |

Klik **Deploy**. Dependency Python tercantum di `requirements.txt`, sedangkan FFmpeg dipasang melalui `packages.txt`. Konfigurasi tema dan batas upload ada di `.streamlit/config.toml`.

Aplikasi memerlukan konfigurasi `[gostream_license]` di **Settings → Secrets** dan aktivasi lisensi sebelum dashboard dapat digunakan. Lihat [panduan lisensi dan akun pemilik](license-worker/README.md) serta contoh `.streamlit/secrets.example.toml`. Kunci berlaku 365 hari sejak aktivasi pertama untuk satu deployment; beberapa browser boleh login ke deployment yang sama. Jangan commit konfigurasi privat atau license key.

Lihat [panduan deployment resmi Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Menjalankan secara lokal

Pasang Python 3.11 dan FFmpeg, lalu pastikan perintah `ffmpeg` tersedia di PATH.

```sh
python -m pip install -r requirements.txt
python -m streamlit run masyasgostream.py
```

Masukkan Stream Key YouTube melalui form aplikasi. Jangan simpan stream key di repository.

## Monitoring dan penyimpanan

Monitoring diperbarui setiap 2 detik selama halaman aktif; ukuran file setiap 15 detik.

- **Stream aktif:** proses FFmpeg aplikasi dengan tujuan RTMP, bukan konfirmasi status live dari YouTube.
- **RAM:** penggunaan container, batas, dan sisa terhadap batas dalam GB desimal. Batas layanan **2,7 GB** dari Workspace Settings pengguna disimpan di `monitoring.toml`; ini nilai konfigurasi layanan, bukan hasil deteksi otomatis. Batas cgroup yang lebih kecil tetap diutamakan. Ubah konfigurasi jika paket layanan berubah. Pembacaan container memakai `memory.current` / `memory.max` pada cgroup v2 atau padanannya pada v1. Jika tidak tersedia, gunakan agregat RSS proses aplikasi dan turunannya tanpa mengasumsikan kapasitas layanan cloud; RSS dapat menghitung memori bersama lebih dari sekali.
- **CPU:** selisih waktu CPU cgroup terhadap waktu nyata, dibandingkan dengan batas quota CPU yang terdeteksi. Jika batas tidak tersedia, tampilkan core terpakai. Fallback menggunakan waktu CPU proses aplikasi dan turunannya.
- **Disk penyimpanan:** kapasitas total, terpakai, dan sisa disk tersedia dari filesystem tempat uploads disimpan. Kapasitas ini dapat dibagi oleh hosting; bukan kuota eksklusif aplikasi atau jaminan seluruh ruang bebas bisa digunakan. Sisa menggunakan byte tersedia yang dilaporkan OS, bukan asumsi total dikurangi terpakai (sebagian disk dapat dicadangkan sistem). Ukuran file project dan uploads ditampilkan terpisah; mengecualikan Git, environment Python, dan cache. Tidak ada kuota storage 20/50 GB yang diasumsikan.
- **Jaringan:** selisih byte kirim/terima interface non-loopback pada namespace jaringan yang terlihat. Bisa mencakup proses lain jika namespace dibagi; pada komputer lokal ini mencakup jaringan komputer. Bukan speed test atau trafik khusus YouTube.

Sumber cgroup dibaca dari `/proc/self/cgroup` dan `/proc/self/mountinfo`. Jika akses resource dibatasi, kartu menampilkan sumber fallback atau data tidak tersedia. Nilai RAM layanan berasal dari konfigurasi terpisah, sedangkan pemakaian dan disk dibaca dari runtime. Sisa terhadap batas RAM bukan ukuran file yang aman di-upload. Lihat [dokumentasi cgroup Linux](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

Media tersimpan di folder `uploads/` pada server, bukan di Git. Penyimpanan ini dapat hilang saat hosting dimulai ulang atau aplikasi di-deploy ulang. Resource dan durasi streaming mengikuti batas penyedia hosting.

## Pemeriksaan monitoring

```sh
python -m unittest discover -s tests -v
```
