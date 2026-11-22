---
name: pdf-to-html-vi
description: >-
  Quy trình mặc định dịch tài liệu PDF sang tiếng Việt, xuất một tệp HTML (kèm bản PDF) dễ đọc trên trình duyệt: dàn lại thành một cột, giữ hình ảnh, bảng biểu và công thức. Dùng khi người dùng gửi hoặc chỉ tới tệp `.pdf` và yêu cầu dịch sang tiếng Việt (vd "dịch file PDF này", "dịch tài liệu này"). KHÔNG dùng khi người dùng muốn giữ hình thức trình bày của bản gốc ("giữ định dạng", "giữ nguyên định dạng", "giữ format", "giữ bố cục", "giữ layout", "bảo toàn layout", "giữ thiết kế", "bảo toàn thiết kế", "giữ cách trình bày", "keep layout"…) — khi đó dùng skill `pdf-to-html-vi-layout`. Yêu cầu về nội dung như "dịch sát nghĩa", "giữ hình ảnh/bảng biểu" vẫn dùng skill này.
---

# `pdf-to-html-vi` — lối vào cho Claude Code

Quy trình gốc dùng chung cho mọi agent nằm ở [`.agents/skills/pdf-to-html-vi/SKILL.md`](../../../.agents/skills/pdf-to-html-vi/SKILL.md). Tệp này chỉ giúp Claude Code tìm thấy skill.

1. Đọc trọn `.agents/skills/pdf-to-html-vi/SKILL.md` và làm theo **đúng từng bước** trong đó. Các liên kết tương đối trong tệp đó (vd `./si_*.md`) tính từ thư mục `.agents/skills/pdf-to-html-vi/`.
2. Áp dụng thêm [`.agents/adapters/claude-code.md`](../../../.agents/adapters/claude-code.md) (đã được nạp qua `CLAUDE.md`; nếu chưa có trong ngữ cảnh thì đọc tệp này trước).
