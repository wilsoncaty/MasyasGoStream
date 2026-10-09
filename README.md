# Masyas Go Stream

Studio streaming YouTube berbasis Streamlit dengan tema putih dan merah.

- Playlist hingga 5 video, atau satu video berulang dengan playlist MP3.
- Sumber video dari perangkat, URL langsung, atau Google Drive.
- Pilihan mode Shorts, jumlah pengulangan, dan durasi siaran.
- Monitoring proses siaran, CPU, memori, dan trafik jaringan server.

## Deploy ke Streamlit Community Cloud

Di [Streamlit Community Cloud](https://share.streamlit.io), pilih **Create app** dan isi:

| Pengaturan | Nilai |
| --- | --- |
| Repository | `wilsoncaty/MasyasGoStream` |
| Branch | `main` |
| Main file path | `tnsstremqu.py` |
| Python version (Advanced settings) | `3.11` |

Klik **Deploy**. Dependency Python tercantum di `requirements.txt`, sedangkan FFmpeg dipasang melalui `packages.txt`. Konfigurasi tema dan batas upload ada di `.streamlit/config.toml`.

Lihat [panduan deployment resmi Streamlit](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Menjalankan secara lokal

Pasang Python 3.11 dan FFmpeg, lalu pastikan perintah `ffmpeg` tersedia di PATH.

```sh
python -m pip install -r requirements.txt
python -m streamlit run tnsstremqu.py
```

Masukkan Stream Key YouTube melalui form aplikasi. Jangan simpan stream key di repository.

## Monitoring dan penyimpanan

Monitoring diperbarui setiap 2 detik selama halaman aktif. Stream aktif menghitung proses FFmpeg aplikasi, bukan konfirmasi status live dari YouTube. CPU dan RAM mengikuti data sistem operasi; pada hosting bersama nilainya dapat mencerminkan host. Trafik jaringan menunjukkan penggunaan aktual, bukan kecepatan maksimum koneksi.

Media tersimpan di folder `uploads/` pada server, bukan di Git. Penyimpanan ini dapat hilang saat hosting dimulai ulang atau aplikasi di-deploy ulang. Resource dan durasi streaming mengikuti batas penyedia hosting.

## Pemeriksaan monitoring

```sh
python -m unittest discover -s tests -v
```
