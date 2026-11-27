# Hướng dẫn cài đặt pingstable

pingstable là một file chạy độc lập: không cần cài Python, không cần quyền admin. Chạy được trên:

- macOS: Mac M-series (Apple Silicon) và Mac Intel
- Windows 10/11 bản 64-bit

---

## macOS

### Cài

1. Mở **Terminal**: bấm `Cmd + Space`, gõ `Terminal`, rồi Enter.
2. Dán lệnh sau vào rồi Enter:

   ```sh
   curl -fsSL https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.sh | sh
   ```

3. Nếu thấy dòng `Đã thêm ... vào PATH`, hãy đóng Terminal rồi mở lại, hoặc chạy `source ~/.zshrc`.
4. Kiểm tra:

   ```sh
   pingstable --version
   ```

Tool được cài vào `~/.local/bin/pingstable`. Script tự chọn bản cho Mac M-series hay Mac Intel.

### Cài thủ công (nếu không muốn chạy script)

1. Vào [trang Releases](https://github.com/TuanPhanDuy/ping-stable/releases/latest) và tải `pingstable-macos-arm64` (Mac M-series) hoặc `pingstable-macos-x64` (Mac Intel).
2. Trong Terminal:

   ```sh
   cd ~/Downloads
   chmod +x pingstable-macos-arm64
   xattr -d com.apple.quarantine pingstable-macos-arm64   # cho phép chạy file tải bằng trình duyệt
   mkdir -p ~/.local/bin && mv pingstable-macos-arm64 ~/.local/bin/pingstable
   ```

### Cập nhật

Chạy lại lệnh cài ở bước 2.

### Gỡ cài đặt

```sh
rm -f ~/.local/bin/pingstable
rm -rf ~/.pingstable
```

Sau đó mở `~/.zshrc` và xoá dòng `export PATH="$HOME/.local/bin:$PATH"` nếu dòng này do pingstable thêm vào.

---

## Windows

### Cài

1. Mở **PowerShell**: bấm phím Windows, gõ `PowerShell`, rồi Enter. Không cần chọn *Run as administrator*.
2. Dán lệnh sau vào rồi Enter:

   ```powershell
   irm https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.ps1 | iex
   ```

3. **Đóng PowerShell và mở lại**, để cửa sổ mới nhận PATH vừa thêm.
4. Kiểm tra:

   ```powershell
   pingstable --version
   ```

Tool được cài vào `%LOCALAPPDATA%\pingstable\pingstable.exe`, và thư mục này được thêm vào PATH của tài khoản bạn.

### Cài thủ công

1. Vào [trang Releases](https://github.com/TuanPhanDuy/ping-stable/releases/latest) và tải `pingstable-windows-x64.exe`.
2. Đổi tên file thành `pingstable.exe`, rồi chạy nó trong PowerShell từ thư mục chứa file: `.\pingstable.exe wifi`.

### Windows Defender / SmartScreen cảnh báo?

File chưa được ký số, nên Windows có thể hiện *"Windows protected your PC"* hoặc Defender chặn. Các tool đóng gói bằng PyInstaller hay bị cảnh báo nhầm kiểu này.

- SmartScreen: bấm **More info** rồi **Run anyway**.
- Muốn chắc file không bị sửa: so mã SHA256 với file `SHA256SUMS` trên trang Release:

  ```powershell
  Get-FileHash "$env:LOCALAPPDATA\pingstable\pingstable.exe" -Algorithm SHA256
  ```

  Trên macOS: `shasum -a 256 ~/.local/bin/pingstable`.

### Cập nhật

Chạy lại lệnh cài ở bước 2.

### Gỡ cài đặt

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\pingstable", "$env:USERPROFILE\.pingstable" -ErrorAction SilentlyContinue
$dir = "$env:LOCALAPPDATA\pingstable"
$path = ([Environment]::GetEnvironmentVariable("Path", "User") -split ";") | Where-Object { $_ -and $_ -ne $dir }
[Environment]::SetEnvironmentVariable("Path", ($path -join ";"), "User")
```

---

## Cài một phiên bản cụ thể

```sh
# macOS
curl -fsSL https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.sh | PINGSTABLE_VERSION=v0.2.0 sh
```

```powershell
# Windows
$env:PINGSTABLE_VERSION = "v0.2.0"; irm https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.ps1 | iex
```

---

## Dùng lần đầu

```sh
pingstable wifi                 # kiểm tra Wi-Fi, gợi ý kênh router nên đặt
pingstable monitor              # mở khi đang trong trận để xem ping theo thời gian thực
pingstable compare --warp       # so sánh đi thẳng và qua Cloudflare WARP (cần cài app 1.1.1.1)
```

- **macOS**: vào một trận PBE rồi chạy `pingstable diagnose` hoặc `pingstable monitor` một lần. Tool tự bắt IP server trận và lưu lại cho các lần sau.
- **Windows**: tool không tự bắt được IP server trận. Khi đang trong trận, mở **Resource Monitor** (`Win + R`, gõ `resmon`), vào tab **Network**, tìm `League of Legends.exe` để xem IP, rồi chạy `pingstable diagnose --target <ip>` một lần. Tool sẽ nhớ IP này cho các lần sau.

## Lỗi thường gặp

| Lỗi | Cách xử lý |
|---|---|
| `command not found: pingstable` (macOS) | Mở Terminal mới, hoặc chạy `source ~/.zshrc` |
| `pingstable is not recognized` (Windows) | Đóng và mở lại PowerShell |
| `Server ... không trả ping` | Chạy khi đang trong trận PBE, hoặc truyền `--target <ip>` |
| `Không đọc được thông tin Wi-Fi` (Windows 11) | Bật **Settings > Privacy & security > Location** để `netsh` đọc được Wi-Fi |
| `Chưa cài Cloudflare WARP` | Cài app miễn phí tại https://one.one.one.one |
