-- v3: provenance for OCR engine selection.
-- image_coverage = share of the PDF page area covered by raster images (0..1).
-- A page with a text layer AND high coverage is a scan whose text layer came from
-- scanner software / stamps — it is OCR'd from the image instead of trusted.
ALTER TABLE pages ADD COLUMN image_coverage REAL;
ALTER TABLE pages ADD COLUMN embedded_chars INTEGER;
