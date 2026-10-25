# Additional source downloads

## ICAI chapter covering composite and mixed supply

Downloaded on 21 October 2026 from the PDF linked by [ICAI's official English study-material listing](https://www.icai.org/post/23057). The user subsequently confirmed permission for retrieval/RAG use including Jina embeddings; the ten-page topic has now been reviewed and pipeline-tested. See [Experiment 03](EXPERIMENT_03_ICAI.md).

- Publication: Intermediate Course, Paper 3 Taxation, Section B Goods and Services Tax, Module 1, Chapter 2 Supply under GST.
- Official PDF: [ICAI chapter download](https://resource.cdn.icai.org/87067bos-aps1530-p2b-m1-may2026-ch2.pdf).
- Full chapter: 104 PDF pages, saved unchanged under the ignored local `data/sources/icai/` directory.
- Matching topic: section 4 on composite and mixed supplies, PDF pages 70-79, printed pages 2.70-2.79. It is a section within a broader chapter, not an exact title/chapter-number match to the firm book.
- The official listing identifies applicability for May 2026, September 2026, and January 2027 exams. The chapter itself states a law cutoff of 30 April 2025; exam applicability is not a claim that all law is current through the exam date.
- Verification: successful download, 104-page reader check, checksum, complete text and visual review of pages 70-79, selected-page Docling conversion, chunking, and Jina retrieval tests. The other 94 pages have not been audited or ingested. No Pinecone indexing was performed.

Local source filename: `ICAI_Intermediate_GST_Chapter_02_Supply_under_GST_May2026.pdf`. Its companion `.source.json` records the source URL, download date, byte size, checksum, page locations, and rights notice.

SHA256: `140dc5f4c5e8c8fe478a9ab416e13b878847ac1f2a9ec4c319ac916e728ffa7b`.

ICAI's listing includes an IPR notice requiring written permission for reproduction, transmission, or storage in retrieval systems. The user explicitly confirmed permission covering retrieval/RAG and Jina embeddings. The experiment proceeds on that confirmation; no permission document was supplied or independently verified. Do not infer additional public-redistribution rights. The source PDF, parsed text, cached vectors, and inspection images are excluded from Git.

The older official BoS chapter initially located stated a 30 April 2023 cutoff. The downloaded source above was chosen instead because its official listing and stated cutoff are newer. No claim is made that this is the newest ICAI publication across every course or portal.

The existing firm-book frozen experiment was not changed by this download.

## Historical notification development sample

Downloaded and fully parsed on 21 October 2026; all 11 pages were read as text and rendered page images. Four reviewed chunks index only the selected renewable-energy and pencil-sharpener provisions. Complete raw conversions are retained. See [Experiment 05](EXPERIMENT_05_NOTIFICATIONS.md) for source evidence, conditions, dates, benchmark scope, and limitations.

| Source | Official PDF | Pages | SHA256 |
|---|---|---:|---|
| 24/2018 Central Tax (Rate) | [GST Council PDF](https://gstcouncil.gov.in/sites/default/files/2024-05/download_2024-05-17t160748.759.pdf) | 4 | `2176fa32a10d683b57690a4959a88c2ad2543cb33979e0ee4fa13da28329177a` |
| 8/2021 Central Tax (Rate) | [CBIC PDF](https://cbic-gst.gov.in/pdf/central-tax-rate/notfctn-08-2021-cgst-rate.pdf) | 6 | `7000b0652372452d703e02b0d99772967c784e03977fa4e1a1d6437f7da3cb08` |
| 3/2023 Central Tax (Rate) | [GST Council PDF](https://www.gstcouncil.gov.in/sites/default/files/2024-05/03_2023-ctr-eng.pdf) | 1 | `b5207a145d96847d00229a99363485ae7657654856c3d06b96c230552088730c` |

Original files and `.source.json` cards are under ignored `data/sources/notifications/`. Reviews bind to both PDF and Docling JSON checksums. Source availability is not treated as evidence of blanket public-redistribution rights; this step performs local development without public redistribution or deployment. No claim is made that these are the latest notifications, a complete amendment history, or sufficient evidence of current law.
