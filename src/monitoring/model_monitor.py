# src/monitoring/model_monitor.py
"""
Model Monitoring and Drift Detection System

Features:
- Data drift detection using statistical tests
- Model performance tracking
- Automated alerts for performance degradation
- Feature importance monitoring
- Prediction distribution analysis
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import json
import warnings
from dataclasses import dataclass, asdict
from scipy import stats
from scipy.stats import ks_2samp, chi2_contingency
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings('ignore')


@dataclass
class DriftReport:
    """Data class for drift detection results"""
    timestamp: str
    feature_name: str
    drift_detected: bool
    drift_score: float
    p_value: float
    drift_type: str
    threshold: float
    recommendation: str


class ModelMonitor:
    """
    Comprehensive model monitoring system for fraud detection
    """
    
    def __init__(
        self,
        reference_data: pd.DataFrame,
        model_name: str = "fraud_detection_ensemble",
        drift_threshold: float = 0.05
    ):
        """
        Initialize model monitor
        
        Args:
            reference_data: Training or validation data as reference
            model_name: Name of the model being monitored
            drift_threshold: P-value threshold for drift detection
        """
        self.reference_data = reference_data
        self.model_name = model_name
        self.drift_threshold = drift_threshold
        
        # Calculate reference statistics
        self.reference_stats = self._calculate_statistics(reference_data)
        
        # Initialize tracking
        self.performance_history = []
        self.drift_history = []
        self.prediction_history = []
        
    def _calculate_statistics(self, data: pd.DataFrame) -> Dict:
        """Calculate statistical properties of data"""
        stats_dict = {}
        
        for column in data.select_dtypes(include=[np.number]).columns:
            stats_dict[column] = {
                'mean': data[column].mean(),
                'std': data[column].std(),
                'min': data[column].min(),
                'max': data[column].max(),
                'q25': data[column].quantile(0.25),
                'q50': data[column].quantile(0.50),
                'q75': data[column].quantile(0.75),
                'skew': data[column].skew(),
                'kurtosis': data[column].kurtosis()
            }
        
        return stats_dict
    
    def detect_data_drift(
        self,
        current_data: pd.DataFrame,
        method: str = 'ks'
    ) -> List[DriftReport]:
        """
        Detect data drift between reference and current data
        
        Args:
            current_data: New data to compare against reference
            method: Statistical test method ('ks', 'chi2', 'psi')
        
        Returns:
            List of drift reports for each feature
        """
        drift_reports = []
        
        for column in self.reference_data.select_dtypes(include=[np.number]).columns:
            if column not in current_data.columns:
                continue
            
            ref_values = self.reference_data[column].dropna()
            curr_values = current_data[column].dropna()
            
            if method == 'ks':
                # Kolmogorov-Smirnov test
                statistic, p_value = ks_2samp(ref_values, curr_values)
                drift_score = statistic
            elif method == 'psi':
                # Population Stability Index
                psi_value = self._calculate_psi(ref_values, curr_values)
                drift_score = psi_value
                p_value = 1.0 if psi_value < 0.1 else 0.0  # PSI thresholds
            else:
                # Default to KS test
                statistic, p_value = ks_2samp(ref_values, curr_values)
                drift_score = statistic
            
            drift_detected = p_value < self.drift_threshold
            
            # Generate recommendation
            if drift_detected:
                if drift_score > 0.3:
                    recommendation = "Critical drift detected. Consider model retraining."
                elif drift_score > 0.2:
                    recommendation = "Significant drift detected. Monitor closely."
                else:
                    recommendation = "Mild drift detected. Continue monitoring."
            else:
                recommendation = "No significant drift detected."
            
            report = DriftReport(
                timestamp=datetime.now().isoformat(),
                feature_name=column,
                drift_detected=drift_detected,
                drift_score=float(drift_score),
                p_value=float(p_value),
                drift_type=method,
                threshold=self.drift_threshold,
                recommendation=recommendation
            )
            
            drift_reports.append(report)
            
        # Store in history
        self.drift_history.extend(drift_reports)
        
        return drift_reports
    
    def _calculate_psi(self, reference: pd.Series, current: pd.Series, bins: int = 10) -> float:
        """
        Calculate Population Stability Index (PSI)
        
        PSI = Σ (current% - reference%) * ln(current% / reference%)
        """
        # Create bins based on reference data
        _, bin_edges = np.histogram(reference, bins=bins)
        
        # Calculate distributions
        ref_counts, _ = np.histogram(reference, bins=bin_edges)
        curr_counts, _ = np.histogram(current, bins=bin_edges)
        
        # Convert to percentages
        ref_percents = ref_counts / len(reference)
        curr_percents = curr_counts / len(current)
        
        # Avoid division by zero
        ref_percents = np.where(ref_percents == 0, 0.0001, ref_percents)
        curr_percents = np.where(curr_percents == 0, 0.0001, curr_percents)
        
        # Calculate PSI
        psi = np.sum((curr_percents - ref_percents) * np.log(curr_percents / ref_percents))
        
        return psi
    
    def track_model_performance(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_pred_proba: np.ndarray,
        timestamp: Optional[datetime] = None
    ) -> Dict:
        """
        Track model performance metrics over time
        
        Args:
            y_true: True labels
            y_pred: Predicted labels
            y_pred_proba: Prediction probabilities
            timestamp: Time of prediction
        
        Returns:
            Performance metrics dictionary
        """
        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score,
            f1_score, roc_auc_score, log_loss
        )
        
        timestamp = timestamp or datetime.now()
        
        metrics = {
            'timestamp': timestamp.isoformat(),
            'accuracy': accuracy_score(y_true, y_pred),
            'precision': precision_score(y_true, y_pred, zero_division=0),
            'recall': recall_score(y_true, y_pred, zero_division=0),
            'f1_score': f1_score(y_true, y_pred, zero_division=0),
            'roc_auc': roc_auc_score(y_true, y_pred_proba),
            'log_loss': log_loss(y_true, y_pred_proba),
            'n_samples': len(y_true),
            'n_positive': int(y_true.sum()),
            'n_predicted_positive': int(y_pred.sum())
        }
        
        # Add to history
        self.performance_history.append(metrics)
        
        # Check for performance degradation
        self._check_performance_degradation(metrics)
        
        return metrics
    
    def _check_performance_degradation(self, current_metrics: Dict):
        """Check if model performance has degraded"""
        if len(self.performance_history) < 10:
            return  # Need sufficient history
        
        # Get recent performance
        recent_f1_scores = [m['f1_score'] for m in self.performance_history[-10:]]
        avg_recent_f1 = np.mean(recent_f1_scores)
        
        # Compare with baseline (first 10 recordings)
        baseline_f1_scores = [m['f1_score'] for m in self.performance_history[:10]]
        avg_baseline_f1 = np.mean(baseline_f1_scores)
        
        # Check for significant degradation
        degradation = (avg_baseline_f1 - avg_recent_f1) / avg_baseline_f1
        
        if degradation > 0.1:  # 10% degradation
            print(f"⚠️ WARNING: Model performance degraded by {degradation:.1%}")
            print(f"   Baseline F1: {avg_baseline_f1:.4f}")
            print(f"   Current F1: {avg_recent_f1:.4f}")
            print("   Consider investigating data quality or retraining the model.")
    
    def analyze_prediction_distribution(
        self,
        predictions: np.ndarray,
        timestamp: Optional[datetime] = None
    ) -> Dict:
        """
        Analyze distribution of model predictions
        
        Args:
            predictions: Array of prediction probabilities
            timestamp: Time of predictions
        
        Returns:
            Distribution analysis results
        """
        timestamp = timestamp or datetime.now()
        
        analysis = {
            'timestamp': timestamp.isoformat(),
            'mean': float(np.mean(predictions)),
            'std': float(np.std(predictions)),
            'min': float(np.min(predictions)),
            'max': float(np.max(predictions)),
            'q25': float(np.quantile(predictions, 0.25)),
            'q50': float(np.quantile(predictions, 0.50)),
            'q75': float(np.quantile(predictions, 0.75)),
            'high_risk_ratio': float(np.mean(predictions > 0.8)),
            'low_risk_ratio': float(np.mean(predictions < 0.2))
        }
        
        # Store in history
        self.prediction_history.append(analysis)
        
        return analysis
    
    def generate_monitoring_report(self) -> Dict:
        """
        Generate comprehensive monitoring report
        
        Returns:
            Complete monitoring report with all metrics
        """
        report = {
            'model_name': self.model_name,
            'report_timestamp': datetime.now().isoformat(),
            'monitoring_period': {
                'start': self.performance_history[0]['timestamp'] if self.performance_history else None,
                'end': self.performance_history[-1]['timestamp'] if self.performance_history else None,
                'duration_days': None
            },
            'performance_summary': self._summarize_performance(),
            'drift_summary': self._summarize_drift(),
            'prediction_summary': self._summarize_predictions(),
            'alerts': self._generate_alerts(),
            'recommendations': self._generate_recommendations()
        }
        
        # Calculate monitoring duration
        if report['monitoring_period']['start'] and report['monitoring_period']['end']:
            start = datetime.fromisoformat(report['monitoring_period']['start'])
            end = datetime.fromisoformat(report['monitoring_period']['end'])
            report['monitoring_period']['duration_days'] = (end - start).days
        
        return report
    
    def _summarize_performance(self) -> Dict:
        """Summarize performance metrics"""
        if not self.performance_history:
            return {}
        
        recent_metrics = self.performance_history[-10:] if len(self.performance_history) >= 10 else self.performance_history
        
        return {
            'current_f1_score': recent_metrics[-1]['f1_score'],
            'avg_f1_score': np.mean([m['f1_score'] for m in recent_metrics]),
            'min_f1_score': min([m['f1_score'] for m in recent_metrics]),
            'max_f1_score': max([m['f1_score'] for m in recent_metrics]),
            'total_predictions': sum([m['n_samples'] for m in self.performance_history]),
            'total_frauds_detected': sum([m['n_predicted_positive'] for m in self.performance_history])
        }
    
    def _summarize_drift(self) -> Dict:
        """Summarize drift detection results"""
        if not self.drift_history:
            return {}
        
        recent_drift = self.drift_history[-100:] if len(self.drift_history) >= 100 else self.drift_history
        
        return {
            'total_features_monitored': len(set([d.feature_name for d in recent_drift])),
            'features_with_drift': len([d for d in recent_drift if d.drift_detected]),
            'critical_drift_features': [
                d.feature_name for d in recent_drift 
                if d.drift_detected and d.drift_score > 0.3
            ],
            'avg_drift_score': np.mean([d.drift_score for d in recent_drift])
        }
    
    def _summarize_predictions(self) -> Dict:
        """Summarize prediction distributions"""
        if not self.prediction_history:
            return {}
        
        recent = self.prediction_history[-10:] if len(self.prediction_history) >= 10 else self.prediction_history
        
        return {
            'current_avg_probability': recent[-1]['mean'],
            'trend': 'increasing' if recent[-1]['mean'] > recent[0]['mean'] else 'decreasing',
            'high_risk_trend': [p['high_risk_ratio'] for p in recent],
            'distribution_stability': np.std([p['std'] for p in recent])
        }
    
    def _generate_alerts(self) -> List[str]:
        """Generate alerts based on monitoring results"""
        alerts = []
        
        # Performance alerts
        if self.performance_history:
            recent_f1 = self.performance_history[-1]['f1_score']
            if recent_f1 < 0.8:
                alerts.append(f"Low F1 score: {recent_f1:.4f}")
        
        # Drift alerts
        recent_drift = [d for d in self.drift_history[-100:] if d.drift_detected]
        if len(recent_drift) > 10:
            alerts.append(f"High drift detected in {len(recent_drift)} features")
        
        # Prediction distribution alerts
        if self.prediction_history:
            recent_high_risk = self.prediction_history[-1]['high_risk_ratio']
            if recent_high_risk > 0.2:
                alerts.append(f"High fraud risk ratio: {recent_high_risk:.1%}")
        
        return alerts
    
    def _generate_recommendations(self) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Based on performance
        if self.performance_history and self.performance_history[-1]['f1_score'] < 0.85:
            recommendations.append("Consider retraining the model with recent data")
        
        # Based on drift
        drift_features = [d.feature_name for d in self.drift_history[-100:] if d.drift_detected]
        if len(set(drift_features)) > 5:
            recommendations.append(f"Investigate data quality for features: {', '.join(set(drift_features)[:5])}")
        
        # Based on predictions
        if self.prediction_history and self.prediction_history[-1]['std'] > 0.3:
            recommendations.append("High variance in predictions - check for data quality issues")
        
        if not recommendations:
            recommendations.append("System operating normally - continue regular monitoring")
        
        return recommendations
    
    def visualize_monitoring_dashboard(self):
        """Create monitoring dashboard visualization"""
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        fig.suptitle('Model Monitoring Dashboard', fontsize=16)
        
        # 1. Performance over time
        if self.performance_history:
            timestamps = [datetime.fromisoformat(m['timestamp']) for m in self.performance_history]
            f1_scores = [m['f1_score'] for m in self.performance_history]
            axes[0, 0].plot(timestamps, f1_scores, marker='o')
            axes[0, 0].set_title('F1 Score Over Time')
            axes[0, 0].set_ylabel('F1 Score')
            axes[0, 0].tick_params(axis='x', rotation=45)
        
        # 2. Drift scores
        if self.drift_history:
            drift_data = pd.DataFrame([asdict(d) for d in self.drift_history[-100:]])
            drift_summary = drift_data.groupby('feature_name')['drift_score'].mean().sort_values(ascending=False)[:10]
            axes[0, 1].barh(drift_summary.index, drift_summary.values)
            axes[0, 1].set_title('Top 10 Features with Drift')
            axes[0, 1].set_xlabel('Average Drift Score')
        
        # 3. Prediction distribution
        if self.prediction_history:
            timestamps = [datetime.fromisoformat(p['timestamp']) for p in self.prediction_history]
            means = [p['mean'] for p in self.prediction_history]
            axes[0, 2].plot(timestamps, means, label='Mean', color='blue')
            axes[0, 2].fill_between(
                timestamps,
                [p['q25'] for p in self.prediction_history],
                [p['q75'] for p in self.prediction_history],
                alpha=0.3, color='blue', label='IQR'
            )
            axes[0, 2].set_title('Prediction Distribution Over Time')
            axes[0, 2].set_ylabel('Probability')
            axes[0, 2].legend()
        
        # 4. Precision-Recall trade-off
        if self.performance_history:
            precision = [m['precision'] for m in self.performance_history]
            recall = [m['recall'] for m in self.performance_history]
            axes[1, 0].scatter(recall, precision, c=range(len(recall)), cmap='viridis')
            axes[1, 0].set_title('Precision-Recall Trade-off')
            axes[1, 0].set_xlabel('Recall')
            axes[1, 0].set_ylabel('Precision')
        
        # 5. Alert frequency
        if self.drift_history:
            drift_counts = pd.DataFrame([asdict(d) for d in self.drift_history])
            drift_counts['hour'] = pd.to_datetime(drift_counts['timestamp']).dt.hour
            hourly_drift = drift_counts.groupby('hour')['drift_detected'].sum()
            axes[1, 1].bar(hourly_drift.index, hourly_drift.values)
            axes[1, 1].set_title('Drift Detections by Hour')
            axes[1, 1].set_xlabel('Hour of Day')
            axes[1, 1].set_ylabel('Drift Count')
        
        # 6. Model metrics summary
        if self.performance_history:
            latest_metrics = self.performance_history[-1]
            metrics_display = {
                'Accuracy': latest_metrics['accuracy'],
                'Precision': latest_metrics['precision'],
                'Recall': latest_metrics['recall'],
                'F1': latest_metrics['f1_score'],
                'AUC': latest_metrics['roc_auc']
            }
            axes[1, 2].bar(metrics_display.keys(), metrics_display.values())
            axes[1, 2].set_title('Current Model Metrics')
            axes[1, 2].set_ylim([0, 1])
            for i, (k, v) in enumerate(metrics_display.items()):
                axes[1, 2].text(i, v + 0.02, f'{v:.3f}', ha='center')
        
        plt.tight_layout()
        plt.show()
    
    def export_monitoring_data(self, filepath: str = 'monitoring_report.json'):
        """Export monitoring data to JSON file"""
        report = self.generate_monitoring_report()
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"✅ Monitoring report exported to {filepath}")


# Example usage
if __name__ == "__main__":
    # Load reference data
    from src.data_processing.generate_data import create_fraud_dataset
    
    # Create reference dataset
    reference_data = create_fraud_dataset(n_samples=10000)
    
    # Initialize monitor
    monitor = ModelMonitor(reference_data, drift_threshold=0.05)
    
    # Simulate monitoring
    for i in range(5):
        # Generate new data (simulating production data)
        current_data = create_fraud_
