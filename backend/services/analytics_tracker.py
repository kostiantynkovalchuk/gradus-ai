import os
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from models import SessionLocal
from models.content import ContentQueue

logger = logging.getLogger(__name__)

class AnalyticsTracker:
    def __init__(self):
        self.page_access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
        self.page_id = os.getenv('FACEBOOK_PAGE_ID')
        self.graph_api_version = 'v18.0'
    
    def get_post_insights(self, post_id: str) -> Dict:
        """
        Get engagement metrics for a Facebook post
        
        Args:
            post_id: Facebook post ID (page_id_post_id format)
            
        Returns:
            Dict with likes, comments, shares, reach, impressions, engagement_rate
        """
        if not self.page_access_token:
            logger.error("Facebook token not configured")
            return {"error": "Token not configured"}
        
        url = f"https://graph.facebook.com/{self.graph_api_version}/{post_id}"
        params = {
            'fields': 'likes.summary(true),comments.summary(true),shares,insights.metric(post_impressions,post_engaged_users,post_clicks)',
            'access_token': self.page_access_token
        }
        
        try:
            response = requests.get(url, params=params, timeout=15)
            result = response.json()
            
            if 'error' in result:
                logger.error(f"Analytics error for {post_id}: {result['error']}")
                return {"error": result['error'].get('message', 'Unknown error')}
            
            metrics = {
                'post_id': post_id,
                'likes': result.get('likes', {}).get('summary', {}).get('total_count', 0),
                'comments': result.get('comments', {}).get('summary', {}).get('total_count', 0),
                'shares': result.get('shares', {}).get('count', 0),
                'engagement_rate': 0,
                'impressions': 0,
                'reach': 0,
                'clicks': 0,
                'collected_at': datetime.now().isoformat()
            }
            
            insights = result.get('insights', {}).get('data', [])
            for insight in insights:
                metric_name = insight.get('name')
                values = insight.get('values', [])
                value = values[0].get('value', 0) if values else 0
                
                if metric_name == 'post_impressions':
                    metrics['impressions'] = value
                elif metric_name == 'post_engaged_users':
                    metrics['reach'] = value
                elif metric_name == 'post_clicks':
                    metrics['clicks'] = value
            
            if metrics['impressions'] > 0:
                total_engagement = metrics['likes'] + metrics['comments'] + metrics['shares']
                metrics['engagement_rate'] = round((total_engagement / metrics['impressions']) * 100, 2)
            
            logger.info(f"Collected metrics for {post_id}: {metrics['likes']} likes, {metrics['comments']} comments")
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get insights for {post_id}: {e}")
            return {"error": str(e)}
    
    def get_best_posting_times(self, days: int = 30) -> Dict:
        """
        Analyze historical posts to find best posting times
        
        Args:
            days: Number of days to analyze (default 30)
            
        Returns:
            Dict with best hours, best days, and statistics
        """
        db = SessionLocal()
        
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            
            posts = db.query(ContentQueue).filter(
                ContentQueue.status == 'posted',
                ContentQueue.created_at >= cutoff_date,
                ContentQueue.extra_metadata.isnot(None)
            ).all()
            
            posts = [p for p in posts if p.extra_metadata and 'fb_post_id' in p.extra_metadata]
            
            if not posts:
                return {
                    "message": "Not enough data yet. Need at least 1 posted article.",
                    "posts_analyzed": 0
                }
            
            performance_by_hour = {}
            performance_by_day = {}
            total_engagement = 0
            posts_with_metrics = 0
            
            for post in posts:
                post_id = post.extra_metadata.get('fb_post_id')
                
                if 'analytics' in post.extra_metadata:
                    metrics = post.extra_metadata['analytics']
                else:
                    metrics = self.get_post_insights(post_id)
                    
                    if 'error' not in metrics:
                        if not post.extra_metadata:
                            post.extra_metadata = {}
                        post.extra_metadata['analytics'] = metrics
                
                if 'error' in metrics:
                    continue
                
                posts_with_metrics += 1
                engagement = metrics.get('likes', 0) + metrics.get('comments', 0) + metrics.get('shares', 0)
                total_engagement += engagement
                
                hour = post.created_at.hour
                if hour not in performance_by_hour:
                    performance_by_hour[hour] = {'count': 0, 'total_engagement': 0}
                
                performance_by_hour[hour]['count'] += 1
                performance_by_hour[hour]['total_engagement'] += engagement
                
                day = post.created_at.strftime('%A')
                if day not in performance_by_day:
                    performance_by_day[day] = {'count': 0, 'total_engagement': 0}
                
                performance_by_day[day]['count'] += 1
                performance_by_day[day]['total_engagement'] += engagement
            
            db.commit()
            
            best_hours = []
            for hour, data in performance_by_hour.items():
                avg = data['total_engagement'] / data['count'] if data['count'] > 0 else 0
                best_hours.append({
                    'hour': f"{hour:02d}:00",
                    'avg_engagement': round(avg, 2),
                    'posts_count': data['count'],
                    'total_engagement': data['total_engagement']
                })
            
            best_hours = sorted(best_hours, key=lambda x: x['avg_engagement'], reverse=True)
            
            best_days = []
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            for day in day_order:
                if day in performance_by_day:
                    data = performance_by_day[day]
                    avg = data['total_engagement'] / data['count'] if data['count'] > 0 else 0
                    best_days.append({
                        'day': day,
                        'avg_engagement': round(avg, 2),
                        'posts_count': data['count'],
                        'total_engagement': data['total_engagement']
                    })
            
            best_days = sorted(best_days, key=lambda x: x['avg_engagement'], reverse=True)
            
            avg_engagement_per_post = round(total_engagement / posts_with_metrics, 2) if posts_with_metrics > 0 else 0
            
            return {
                'summary': {
                    'posts_analyzed': posts_with_metrics,
                    'date_range_days': days,
                    'total_engagement': total_engagement,
                    'avg_engagement_per_post': avg_engagement_per_post
                },
                'best_hours': best_hours[:5],
                'best_days': best_days,
                'recommendations': self._generate_recommendations(best_hours, best_days, posts_with_metrics)
            }
            
        finally:
            db.close()
    
    def _generate_recommendations(self, best_hours: List, best_days: List, posts_count: int) -> List[str]:
        """Generate actionable recommendations based on data"""
        recommendations = []
        
        if posts_count < 5:
            recommendations.append(f"⚠️ Limited data: Only {posts_count} posts analyzed. Need at least 10 posts for reliable insights.")
        
        if best_hours:
            top_hour = best_hours[0]
            recommendations.append(f"🕐 Best posting time: {top_hour['hour']} (avg {top_hour['avg_engagement']} engagement)")
        
        if best_days:
            top_day = best_days[0]
            recommendations.append(f"📅 Best posting day: {top_day['day']} (avg {top_day['avg_engagement']} engagement)")
        
        if len(best_hours) >= 3:
            top_3_hours = [h['hour'] for h in best_hours[:3]]
            recommendations.append(f"⭐ Optimal posting windows: {', '.join(top_3_hours)}")
        
        return recommendations
    
    def get_recent_posts_performance(self, limit: int = 10) -> List[Dict]:
        """Get performance summary for recent posts"""
        db = SessionLocal()
        
        try:
            posts = db.query(ContentQueue).filter(
                ContentQueue.status == 'posted',
                ContentQueue.extra_metadata.isnot(None)
            ).order_by(ContentQueue.created_at.desc()).limit(limit).all()
            
            results = []
            
            for post in posts:
                if not post.extra_metadata or 'fb_post_id' not in post.extra_metadata:
                    continue
                
                post_id = post.extra_metadata['fb_post_id']
                
                if 'analytics' in post.extra_metadata:
                    metrics = post.extra_metadata['analytics']
                else:
                    metrics = self.get_post_insights(post_id)
                    if 'error' not in metrics:
                        if not post.extra_metadata:
                            post.extra_metadata = {}
                        post.extra_metadata['analytics'] = metrics
                
                if 'error' in metrics:
                    continue
                
                results.append({
                    'id': post.id,
                    'title': post.translated_title or 'Untitled',
                    'created_at': post.created_at.isoformat() if post.created_at else None,
                    'post_url': post.extra_metadata.get('fb_post_url', ''),
                    'metrics': {
                        'likes': metrics.get('likes', 0),
                        'comments': metrics.get('comments', 0),
                        'shares': metrics.get('shares', 0),
                        'engagement_rate': metrics.get('engagement_rate', 0),
                        'impressions': metrics.get('impressions', 0)
                    }
                })
            
            db.commit()
            return results
            
        finally:
            db.close()

analytics_tracker = AnalyticsTracker()
