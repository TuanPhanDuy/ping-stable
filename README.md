# pingstable

Tool dòng lệnh giúp tìm và giảm lag khi chơi game ở server xa, ví dụ chơi TFT PBE (server Bắc Mỹ) từ Việt Nam. Chạy trên macOS và Windows.

Từ Việt Nam sang Bắc Mỹ, ping thấp nhất cũng khoảng 180–250ms vì khoảng cách vật lý, không tool nào hạ được dưới mức đó. Thứ làm game giật thường là **jitter** (ping lên xuống thất thường) và **mất gói**, chủ yếu đến từ Wi-Fi trong nhà. Tool này tìm ra các nguyên nhân đó và gợi ý cách sửa.

## Cài đặt

**macOS** (Terminal):

```sh
curl -fsSL https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.sh | sh
```

**Windows** (PowerShell):

```powershell
irm https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.ps1 | iex
```

Hướng dẫn chi tiết (cài thủ công, cập nhật, gỡ cài đặt, cảnh báo của Windows Defender, lỗi thường gặp): xem [INSTALL.md](INSTALL.md).

## Cách dùng

```sh
pingstable wifi                  # sóng, nhiễu, kênh đè nhau, app ngốn mạng + kênh router nên đặt
pingstable diagnose              # ping/jitter/mất gói tới router và server game, traceroute, kết luận
pingstable monitor               # theo dõi ping liên tục khi đang chơi, báo spike
sudo pingstable fix              # macOS: tắt awdl0 (AirDrop/Handoff) gây spike trên Wi-Fi; --revert để bật lại
pingstable compare --warp        # đo đi thẳng và qua Cloudflare WARP, chọn tuyến tốt hơn, trả WARP về như cũ
pingstable compare --routes "Wi-Fi nhà" "4G Viettel"   # đổi mạng bằng tay giữa các lượt đo
pingstable relay root@1.2.3.4    # so sánh đi thẳng với đi qua VPS, in cấu hình WireGuard split tunnel
```

### Giảm ping miễn phí, không cần VPS

`compare` đo cùng một server game qua nhiều tuyến mạng, rồi cho biết tuyến nào ít giật nhất. Cách tính điểm ưu tiên jitter và mất gói hơn ping trung bình.

- **Cloudflare WARP**: cài app 1.1.1.1 (miễn phí), rồi chạy `pingstable compare --warp`. Tool tự bật và tắt WARP để đo, xong thì trả về đúng trạng thái ban đầu, kể cả khi bị lỗi hoặc bạn bấm Ctrl+C.
- **Nhà mạng khác**: phát 4G/5G từ điện thoại dùng nhà mạng khác với mạng nhà. Mỗi nhà mạng đi ra nước ngoài theo tuyến khác nhau.

Mỗi lần bắt được IP server trận, tool lưu lại vào `~/.pingstable/last_target`. Nhờ vậy `compare` vẫn đo được sau khi đã thoát game.

`diagnose` và `monitor` tự tìm IP server trận khi đang chơi (chỉ trên macOS). Trên Windows, xem IP trong Resource Monitor (`resmon`) > Network > `League of Legends.exe`, rồi truyền vào bằng `--target <ip>`.

## Khác nhau giữa macOS và Windows

| | macOS | Windows |
|---|---|---|
| Phân tích Wi-Fi | đủ: dBm, SNR, MCS, độ rộng kênh | không có SNR/MCS/độ rộng kênh (netsh không cung cấp) |
| App ngốn mạng | có | chưa có |
| Tự tìm IP server trận | có | không, dùng `--target` |
| `fix` | tắt awdl0 | không có |

## An toàn

Ngoài `fix`, tool chỉ gọi các lệnh hệ thống dùng để đọc thông tin (`ping`, `traceroute`/`tracert`, `netsh wlan show`, `system_profiler`, `nettop`...). Tool không đọc bộ nhớ hay can thiệp vào game, không sửa gói tin, không đổi cấu hình mạng. Test trong `test_pingstable.py` kiểm tra các điều này.

## Phát triển

```sh
python3 -m unittest -v test_pingstable
```

Phát hành: tăng `__version__` trong `pingstable.py`, commit, rồi `git tag vX.Y.Z && git push --tags`. GitHub Actions sẽ chạy test trên macOS và Windows, build file chạy độc lập bằng PyInstaller, rồi tạo Release.
