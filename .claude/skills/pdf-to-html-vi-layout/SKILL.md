---
name: pdf-to-html-vi-layout
description: >-
  Quy trình dịch tệp PDF sang HTML/PDF tiếng Việt theo chế độ BẢO TOÀN TỐI ĐA THIẾT KẾ & BỐ CỤC TỪNG TRANG (tách pha dịch Markdown trung gian trước khi dựng HTML/CSS cô lập từng trang, không gắn `reader_shell.html`). SKILL này CHỈ kích hoạt khi người dùng nêu rõ các yêu cầu như "bảo toàn thiết kế", "bảo toàn layout", "giữ thiết kế", "giữ layout", "giữ nguyên định dạng"; nếu chỉ yêu cầu dịch sang tiếng Việt thì dùng skill mặc định `pdf-to-html-vi`.
---

# `pdf-to-html-vi-layout` — lối vào cho Claude Code

Quy trình gốc dùng chung cho mọi agent nằm ở [`.agents/skills/pdf-to-html-vi-layout/SKILL.md`](../../../.agents/skills/pdf-to-html-vi-layout/SKILL.md). Tệp này chỉ giúp Claude Code tìm thấy skill.

1. Đọc trọn `.agents/skills/pdf-to-html-vi-layout/SKILL.md` và làm theo **đúng từng bước** trong đó. Các liên kết tương đối trong tệp đó (vd `./si_*.md`) tính từ thư mục `.agents/skills/pdf-to-html-vi-layout/`.
2. Áp dụng thêm [`.agents/adapters/claude-code.md`](../../../.agents/adapters/claude-code.md) (đã được nạp qua `CLAUDE.md`; nếu chưa có trong ngữ cảnh thì đọc tệp này trước).
