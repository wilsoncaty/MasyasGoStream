# Lisensi Masyas Go Stream

Worker ini khusus `masyasgostream`. Tabel `gostream_*` berbagi database D1 dengan layanan lama, tetapi tidak membaca atau mengubah tabel produk lama. Kunci produk lama tidak diterima di sini. Untuk produk baru, gunakan product ID, penerbit kunci, dan validasi produk tersendiri.

## Aturan

- Kunci dibuat oleh penjual. Masa aktif 365 hari dimulai pada aktivasi pertama menurut waktu server.
- Satu lisensi terikat pada identitas instalasi dan URL deployment. Identitas disimpan tetap di Streamlit Secrets, bukan dibuat ulang setiap aplikasi berjalan.
- Beberapa browser boleh login dengan akun pemilik yang sama. Sesi masing-masing berlaku 8 jam; keluar dari satu browser tidak mengeluarkan browser lain.
- Username dan password dibuat saat aktivasi pertama. Password disimpan sebagai hash PBKDF2 bersalt dengan pepper rahasia Worker; D1 tidak menyimpan password, kunci lisensi, atau token sesi mentah.
- Mulai siaran selalu memeriksa server. Kedaluwarsa atau layanan lisensi tidak tersedia menolak mulai siaran baru, tanpa mengirim perintah Stop ke FFmpeg yang berjalan.
- Lisensi kedaluwarsa/dicabut tetap mengizinkan pemilik login untuk menghentikan siaran. Revoke membatalkan sesi lama; pemilik dapat login ulang dengan akses mulai siaran diblokir.
- Melepas instalasi, mereset aktivasi, atau reboot tidak mengulang masa aktif. Perpanjangan menambah hari dari tanggal kedaluwarsa atau waktu sekarang, mana yang lebih akhir.
- Login berlaku untuk pemilik deployment, bukan sistem akun pelanggan SaaS terpisah. Semua browser pemilik mengendalikan playlist dan proses yang sama. Aplikasi mendukung satu proses siaran per proses server Streamlit.

Pembeli yang mendapatkan source code bisa menghapus pemeriksaan lisensi atau menyalin identitas deployment. Binding ini menegakkan aturan pada aplikasi asli, bukan DRM yang kebal modifikasi. Fungsi penting harus dipindahkan ke server penjual jika memerlukan pembatasan yang lebih kuat.

## Deploy backend (penjual)

Konfigurasi akun/database ada di `wrangler.toml`. Jalankan dari root repository setelah login Wrangler:

```sh
npx wrangler d1 execute masyas-licenses --remote --file license-worker/schema.sql --config license-worker/wrangler.toml
npx wrangler deploy --config license-worker/wrangler.toml
npx wrangler secret bulk .private/cloudflare-license-secrets.json --config license-worker/wrangler.toml
```

File JSON rahasia berisi `ADMIN_TOKEN` dan `AUTH_PEPPER`, masing-masing nilai acak minimal 32 byte. Simpan cadangan privat. Jangan mengganti pepper tanpa prosedur reset password pemilik karena hash lama bergantung padanya. Jangan berikan rahasia admin/pepper kepada pembeli.

Simpan konfigurasi alat admin di `.private/license-admin.json`:

```json
{"api_url":"https://YOUR-WORKER.workers.dev","admin_token":"YOUR_PRIVATE_ADMIN_TOKEN"}
```

## Menerbitkan dan mengelola lisensi

```sh
python tools/manage_licenses.py issue --label "Pelanggan A" --output .private/pelanggan-a.json
python tools/manage_licenses.py list
python tools/manage_licenses.py extend --license-id UUID --days 365
python tools/manage_licenses.py revoke --license-id UUID
python tools/manage_licenses.py restore --license-id UUID
python tools/manage_licenses.py reset-installation --license-id UUID
python tools/manage_licenses.py reset-owner --license-id UUID
```

`reset-installation` mempertahankan akun. `reset-owner` menghapus akun dan binding sehingga pemegang kunci dapat membuat akun baru; keduanya mempertahankan tanggal kedaluwarsa. Gunakan reset-owner hanya setelah memverifikasi pemilik. Restore tidak memperpanjang tanggal kedaluwarsa. Daftar admin menampilkan maksimal 100 lisensi terbaru.

Kunci lisensi mentah hanya dikembalikan saat penerbitan dan disimpan alat ke file privat. Berikan hanya kunci pelanggan yang bersangkutan serta konfigurasi instalasinya melalui jalur privat.

## Memasang aplikasi pembeli

```sh
python tools/generate_installation.py --api-url https://YOUR-WORKER.workers.dev --deployment-url https://YOUR-APP.streamlit.app --output .private/customer-secrets.toml
```

1. Tempel isi file TOML tersebut ke **Settings → Secrets** pada aplikasi Streamlit, lalu simpan. Pertahankan section rahasia lain jika sudah ada.
2. Buka aplikasi, pilih **Aktivasi pertama / pindah deployment**, masukkan kunci, lalu buat username dan password minimal 12 karakter.
3. Browser berikutnya cukup login dengan akun yang sama. Jangan membuat installation ID baru saat reboot/redeploy.
4. Untuk pindah URL/deployment, hentikan siaran dan gunakan **Lepas aktivasi deployment**. Buat konfigurasi tujuan dan aktivasi memakai kunci serta akun lama. Masa aktif tidak direset.

Untuk lokal, hasilkan konfigurasi dengan deployment URL `http://localhost:8501`, lalu simpan sebagai `.streamlit/secrets.toml`. Gunakan lisensi pengujian terpisah dari produksi. File `.private/`, `.streamlit/secrets.toml`, dan `.dev.vars` diabaikan Git; jangan menyalin rahasia ke source code.

## Verifikasi

```sh
python -m unittest discover -s tests -v
cd license-worker
npm test
```

Tes Worker menggunakan Node.js 22.13+ dengan `node:sqlite`; produksi berjalan pada Cloudflare Workers. Tes mencakup aktivasi bersamaan, multi-browser, pemisahan produk, kedaluwarsa, reset, logout, pencabutan, perpanjangan, serta pembatasan percobaan login. Tes Python memastikan dashboard terkunci sebelum login dan mulai siaran gagal aman jika verifikasi gagal.
