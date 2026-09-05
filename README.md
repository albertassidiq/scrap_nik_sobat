# Paket Scrape Mitra KEPKA SE26

Folder ini adalah paket mandiri untuk menjalankan script scrape Mitra KEPKA SE26.

Isi utama:

- `config-automasi-pengajuan.txt`: konfigurasi akun SSO dan kegiatan.
- `pilih_kegiatan_kepka.py`: login lalu berhenti setelah memilih kegiatan.
- `scrape_kepka_full_nik.py`: scrape tabel dan NIK dari modal detail.
- `scrape_kepka_rekening.py`: scrape tabel, nama bank, nomor rekening, dan pemilik rekening dari modal detail.
- `run_pilih_kegiatan_kepka.cmd`: test login + pilih kegiatan saja.
- `run_scrape_kepka_full_nik.cmd`: jalankan scrape penuh dengan mode resume.
- `run_scrape_kepka_rekening.cmd`: jalankan scrape rekening penuh dengan mode resume.
- `setup_venv.cmd`: bikin ulang venv kalau venv bawaan tidak jalan setelah dipindah komputer.
- `venv/`: Python virtual environment yang sudah berisi dependency.
- `requirements.txt`: daftar dependency kalau perlu bikin ulang venv.

Output seperti JSON, Excel, dan screenshot sengaja tidak disertakan di paket ini.

## Cara ganti akun

Edit `config-automasi-pengajuan.txt`:

```txt
Username=isi_username_sso
Password=isi_password_sso
Sensus/Survei=(SE2026) SENSUS EKONOMI 2026
Kegiatan=PENDATAAN
```

Biasanya yang diganti cukup `Username` dan `Password`.

## Cara test login dan pilih kegiatan

Double click:

```txt
run_pilih_kegiatan_kepka.cmd
```

Script ini hanya login, pilih provinsi/kabupaten/sensus/kegiatan, lalu berhenti. Tidak klik assign/tawarkan.

## Cara menjalankan scrape

Double click:

```txt
run_scrape_kepka_full_nik.cmd
```

Untuk scrape rekening:

```txt
run_scrape_kepka_rekening.cmd
```

Atau lewat CMD:

```bat
cd /d "LOKASI_FOLDER_INI"
run_scrape_kepka_full_nik.cmd
```

Runner memakai `--resume`, jadi kalau proses berhenti di tengah, jalankan ulang command yang sama. Row yang sudah sukses akan diskip dari file JSON progress.

Output rekening tersimpan di `scrap_kepka_rekening.json`.

## Kalau muncul captcha / Akses Dibatasi

Kalau browser menampilkan captcha atau halaman `Akses Dibatasi`, selesaikan manual di browser yang sedang terbuka.

Jangan tutup browser saat script menunggu captcha. Setelah captcha selesai, script akan lanjut sendiri.

Kalau browser terlanjur tertutup atau script berhenti, jalankan ulang `run_scrape_kepka_full_nik.cmd`.

## Kalau venv bermasalah setelah dipindah komputer

Kalau `venv` bawaan tidak jalan di komputer lain, bikin ulang dari folder ini:

```bat
rename venv venv_lama
setup_venv.cmd
```

Setelah itu jalankan lagi file `.cmd`.

## Catatan keamanan

File config berisi akun login. Simpan dan bagikan paket ini hanya ke orang yang berwenang.
