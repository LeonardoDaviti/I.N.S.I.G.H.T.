"""
Test Reporter for I.N.S.I.G.H.T. Mark II Testing Suite
"""

import json
from datetime import datetime
from pathlib import Path

class TestReporter:
    """Generates comprehensive test reports"""
    
    def generate_report(self, test_results, available_connectors):
        """Generate a comprehensive test report"""
        timestamp = datetime.now().isoformat()
        
        # Calculate statistics
        total_tests = len(test_results)
        passed_tests = sum(1 for r in test_results if r['success'])
        failed_tests = total_tests - passed_tests
        
        # User validation stats (for manual mode)
        user_passed = sum(1 for r in test_results if r.get('user_validation') == 'passed')
        user_failed = sum(1 for r in test_results if r.get('user_validation') == 'failed')
        user_skipped = sum(1 for r in test_results if r.get('user_validation') == 'skipped')
        
        total_posts = sum(r['posts_fetched'] for r in test_results)
        total_execution_time = sum(r['execution_time'] for r in test_results)
        rate_limiting_incidents = sum(1 for r in test_results if r.get('rate_limiting_detected', False))
        
        # Performance analysis
        performance_by_connector = {}
        for result in test_results:
            mission = result['mission']
            connector = mission.split('_')[0]  # Extract connector from mission name
            
            if connector not in performance_by_connector:
                performance_by_connector[connector] = {
                    'total_tests': 0,
                    'total_posts': 0,
                    'total_time': 0,
                    'avg_posts_per_second': 0
                }
            
            perf = performance_by_connector[connector]
            perf['total_tests'] += 1
            perf['total_posts'] += result['posts_fetched']
            perf['total_time'] += result['execution_time']
            
            if perf['total_time'] > 0:
                perf['avg_posts_per_second'] = perf['total_posts'] / perf['total_time']
        
        # Build report
        report = {
            'metadata': {
                'timestamp': timestamp,
                'testing_suite_version': '2.4.0',
                'insight_version': 'Mark II v2.4',
                'available_connectors': available_connectors
            },
            'summary': {
                'statistics': {
                    'total_tests': total_tests,
                    'passed': passed_tests,
                    'failed': failed_tests,
                    'success_rate': (passed_tests / total_tests * 100) if total_tests > 0 else 0,
                    'user_validation': {
                        'passed': user_passed,
                        'failed': user_failed,
                        'skipped': user_skipped
                    },
                    'total_posts': total_posts,
                    'total_execution_time': total_execution_time,
                    'avg_execution_time': total_execution_time / total_tests if total_tests > 0 else 0,
                    'rate_limiting_incidents': rate_limiting_incidents
                },
                'performance_by_connector': performance_by_connector,
                'connectors_tested': list(performance_by_connector.keys())
            },
            'results': test_results,
            'recommendations': self._generate_recommendations(test_results, performance_by_connector)
        }
        
        return report
    
    def _generate_recommendations(self, test_results, performance_data):
        """Generate recommendations based on test results"""
        recommendations = []
        
        # Check for consistent failures
        failed_missions = {}
        for result in test_results:
            if not result['success']:
                mission = result['mission']
                failed_missions[mission] = failed_missions.get(mission, 0) + 1
        
        for mission, failures in failed_missions.items():
            if failures > 1:
                recommendations.append(f"Mission '{mission}' failed {failures} times - investigate connector stability")
        
        # Check performance issues
        for connector, perf in performance_data.items():
            if perf['avg_posts_per_second'] < 1.0:
                recommendations.append(f"{connector.title()} connector is slow ({perf['avg_posts_per_second']:.1f} posts/sec) - consider optimization")
        
        # Check rate limiting
        rate_limited_tests = [r for r in test_results if r.get('rate_limiting_detected')]
        if rate_limited_tests:
            recommendations.append(f"Rate limiting detected in {len(rate_limited_tests)} tests - consider increasing delays")
        
        if not recommendations:
            recommendations.append("All tests performed within expected parameters")
        
        return recommendations
    
    def generate_html_report(self, report_data):
        """Generate an HTML version of the test report"""
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>I.N.S.I.G.H.T. Mark II - Test Report</title>
    <style>
        body {{ font-family: 'Courier New', monospace; background: #0a0a0a; color: #00ff00; margin: 0; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ text-align: center; border: 2px solid #00ff00; padding: 20px; margin-bottom: 30px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-box {{ border: 1px solid #00ff00; padding: 15px; text-align: center; }}
        .test-result {{ border: 1px solid #333; margin: 10px 0; padding: 15px; }}
        .passed {{ border-left: 5px solid #00ff00; }}
        .failed {{ border-left: 5px solid #ff0000; }}
        .recommendations {{ background: #1a1a1a; border: 1px solid #ffff00; padding: 20px; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>I.N.S.I.G.H.T. Mark II - Test Report</h1>
            <p>Generated: {report_data['metadata']['timestamp']}</p>
            <p>Connectors: {', '.join(report_data['metadata']['available_connectors'])}</p>
        </div>
        
        <div class="stats">
            <div class="stat-box">
                <h3>Total Tests</h3>
                <p>{report_data['summary']['statistics']['total_tests']}</p>
            </div>
            <div class="stat-box">
                <h3>Success Rate</h3>
                <p>{report_data['summary']['statistics']['success_rate']:.1f}%</p>
            </div>
            <div class="stat-box">
                <h3>Posts Fetched</h3>
                <p>{report_data['summary']['statistics']['total_posts']}</p>
            </div>
            <div class="stat-box">
                <h3>Execution Time</h3>
                <p>{report_data['summary']['statistics']['total_execution_time']:.1f}s</p>
            </div>
        </div>
        
        <h2>Test Results</h2>
        """
        
        for result in report_data['results']:
            status_class = 'passed' if result['success'] else 'failed'
            status_icon = '✅' if result['success'] else '❌'
            
            html_content += f"""
        <div class="test-result {status_class}">
            <h3>{status_icon} {result['name']}</h3>
            <p><strong>Mission:</strong> {result['mission']}</p>
            <p><strong>Posts Fetched:</strong> {result['posts_fetched']}</p>
            <p><strong>Execution Time:</strong> {result['execution_time']:.2f}s</p>
            <p><strong>Output Formats:</strong> {', '.join(result.get('output_formats_tested', []))}</p>
            {f'<p><strong>Errors:</strong> {", ".join(result["errors"])}</p>' if result.get('errors') else ''}
        </div>
            """
        
        html_content += f"""
        <div class="recommendations">
            <h2>Recommendations</h2>
            <ul>
                {''.join(f'<li>{rec}</li>' for rec in report_data['recommendations'])}
            </ul>
        </div>
    </div>
</body>
</html>
        """
        
        return html_content