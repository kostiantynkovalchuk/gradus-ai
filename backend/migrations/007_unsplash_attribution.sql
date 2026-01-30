-- Migration: Add Unsplash attribution columns to content_queue
-- Date: 2026-01-30
-- Purpose: Store image attribution data for Unsplash API compliance

ALTER TABLE content_queue
ADD COLUMN IF NOT EXISTS image_credit VARCHAR(255),
ADD COLUMN IF NOT EXISTS image_credit_url VARCHAR(500),
ADD COLUMN IF NOT EXISTS image_photographer VARCHAR(255),
ADD COLUMN IF NOT EXISTS unsplash_image_id VARCHAR(100);

-- Add index for unsplash_image_id for duplicate checking
CREATE INDEX IF NOT EXISTS idx_content_queue_unsplash_id ON content_queue(unsplash_image_id);

COMMENT ON COLUMN content_queue.image_credit IS 'Attribution text: Photo by {name} on Unsplash';
COMMENT ON COLUMN content_queue.image_credit_url IS 'Photographer profile URL on Unsplash';
COMMENT ON COLUMN content_queue.image_photographer IS 'Photographer name';
COMMENT ON COLUMN content_queue.unsplash_image_id IS 'Unique Unsplash photo ID for duplicate prevention';
