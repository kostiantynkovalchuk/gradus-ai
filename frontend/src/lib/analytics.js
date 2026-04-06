/**
 * Google Analytics 4 event helpers for Gradus Media dashboard.
 * Measurement ID: G-XXXXXXXXXX — replace with real ID when GA4 property is created.
 *
 * Usage:
 *   import { trackEvent } from '../lib/analytics'
 *   trackEvent('chat_started')
 *   trackEvent('quick_question_clicked', { question: 'Як підвищити маржу?' })
 */

const GA_ID = 'G-XXXXXXXXXX';

function gtag(...args) {
  if (typeof window !== 'undefined' && window.gtag) {
    window.gtag(...args);
  }
}

export function trackPageView(path) {
  gtag('config', GA_ID, { page_path: path });
}

export function trackEvent(eventName, params = {}) {
  gtag('event', eventName, params);
}

// ─── Named event helpers ─────────────────────────────────────────────────────

/** Fired when user submits a chat message (Alex Gradus chat). */
export function trackChatStarted(questionPreview = '') {
  trackEvent('chat_started', { question_preview: questionPreview.slice(0, 80) });
}

/** Fired when user clicks a preset quick-start question button. */
export function trackQuickQuestionClicked(questionText) {
  trackEvent('quick_question_clicked', { question: questionText });
}

/** Fired when user submits their email in the email gate. */
export function trackEmailSubmitted() {
  trackEvent('email_submitted');
}

/** Fired when user clicks a "Start Trial" / "Спробувати" button on a pricing tier. */
export function trackTrialStarted(tierName) {
  trackEvent('trial_started', { tier: tierName });
}

/** Fired when user views the pricing / plans page. */
export function trackPlanViewed(tierName = '') {
  trackEvent('plan_viewed', { tier: tierName });
}

/** Fired when content item is approved in the approval workflow. */
export function trackContentApproved(contentId) {
  trackEvent('content_approved', { content_id: contentId });
}

/** Fired when content item is rejected. */
export function trackContentRejected(contentId, reason = '') {
  trackEvent('content_rejected', { content_id: contentId, reason });
}
