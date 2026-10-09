"""
Example usage of the Interpretation API integration in Django views.

This module demonstrates how to integrate interpretation calls into
your application logic and API endpoints.
"""

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from backendapi.interpretation_service import (
    get_summary,
    answer_question,
    check_health,
    InterpretationServiceError,
)


# ============================================================================
# EXAMPLE 1: Simple summary endpoint
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def get_portfolio_summary_view(request):
    """
    Generate a summary for a portfolio after model calculation.
    
    Expected request body:
    {
        "portfolio_id": "p-123",
        "model_output": {
            "portfolio_summary": {
                "portfolio_aal_kes": {"ml_augmented": 607333848.44}
            },
            "building_risk_summary": [
                {"building_id": "NBO-0316", "risk_score": 87.4},
                {"building_id": "NBO-1042", "risk_score": 81.2}
            ]
        }
    }
    """
    try:
        model_output = request.data.get('model_output')
        if not model_output:
            return Response(
                {'error': 'model_output is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Call the interpretation service
        result = get_summary(model_output)
        
        return Response({
            'portfolio_id': request.data.get('portfolio_id'),
            'summary': result.get('summary'),
            'source': result.get('source'),
            'interpretation_only': result.get('interpretation_only', True),
        })
    
    except InterpretationServiceError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_502_BAD_GATEWAY
        )


# ============================================================================
# EXAMPLE 2: Q&A endpoint for underwriter questions
# ============================================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def ask_question_view(request):
    """
    Answer an underwriter's question about a portfolio.
    
    Expected request body:
    {
        "portfolio_id": "p-123",
        "question": "Which building has the highest risk score?",
        "context": {
            "building_risk_summary": [
                {"building_id": "NBO-0316", "risk_score": 87.4},
                {"building_id": "NBO-1042", "risk_score": 81.2}
            ]
        }
    }
    """
    try:
        question = request.data.get('question')
        context = request.data.get('context')
        
        if not question:
            return Response(
                {'error': 'question is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if not context:
            return Response(
                {'error': 'context is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Call the interpretation service
        result = answer_question(question, context)
        
        return Response({
            'question': question,
            'answer': result.get('answer'),
            'source': result.get('source'),
            'interpretation_only': result.get('interpretation_only', True),
        })
    
    except InterpretationServiceError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_502_BAD_GATEWAY
        )


# ============================================================================
# EXAMPLE 3: Chained flow - upload → model → interpretation
# ============================================================================

def upload_and_interpret_workflow(upload_data, model_output):
    """
    Example workflow: process upload, run model, then interpret results.
    """
    from backendapi import model_api
    
    # Step 1: Upload and extract data (using your existing upload_api)
    extracted = upload_data  # Already extracted from document
    
    # Step 2: Run model (using your existing model_api)
    model_result = model_api._proxy_model_api(
        '/model/run',
        method='POST',
        payload={'portfolio_id': extracted['portfolio_id']}
    )
    
    # Step 3: Interpret results
    try:
        interpretation = get_summary(model_result)
        return {
            'status': 'success',
            'model_run_id': model_result['run_id'],
            'summary': interpretation['summary'],
            'interpretation_source': interpretation['source'],
        }
    except InterpretationServiceError as e:
        return {
            'status': 'model_ok_but_interpretation_failed',
            'error': str(e),
            'model_run_id': model_result['run_id'],
        }


# ============================================================================
# EXAMPLE 4: Caching interpretation results
# ============================================================================

from django.core.cache import cache
import hashlib
import json


def get_cached_summary(model_output, cache_ttl=3600):
    """
    Get interpretation summary, using cache to avoid repeated API calls
    for the same model output.
    
    Args:
        model_output: Model calculation output
        cache_ttl: Cache time-to-live in seconds (default 1 hour)
    """
    # Create a cache key based on the model output hash
    output_json = json.dumps(model_output, sort_keys=True)
    cache_key = f"interpretation_summary_{hashlib.md5(output_json.encode()).hexdigest()}"
    
    # Try to get from cache first
    cached_result = cache.get(cache_key)
    if cached_result:
        return {'cached': True, **cached_result}
    
    # Cache miss - call the service
    try:
        result = get_summary(model_output)
        # Store in cache
        cache.set(cache_key, result, cache_ttl)
        return {'cached': False, **result}
    except InterpretationServiceError as e:
        # Could optionally store a "service unavailable" result
        raise


# ============================================================================
# EXAMPLE 5: Batch interpretation for multiple portfolios
# ============================================================================

def batch_interpret_portfolios(portfolios: list) -> list:
    """
    Generate summaries for multiple portfolios.
    
    Args:
        portfolios: List of dicts with 'id' and 'model_output' keys
    
    Returns:
        List of dicts with 'id', 'summary', 'error' (if any)
    """
    results = []
    
    for portfolio in portfolios:
        try:
            summary = get_summary(portfolio['model_output'])
            results.append({
                'portfolio_id': portfolio['id'],
                'summary': summary['summary'],
                'success': True,
            })
        except InterpretationServiceError as e:
            results.append({
                'portfolio_id': portfolio['id'],
                'error': str(e),
                'success': False,
            })
    
    return results


# ============================================================================
# EXAMPLE 6: Health check endpoint
# ============================================================================

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def service_health_view(request):
    """Check if interpretation service is available."""
    is_healthy = check_health()
    
    return Response({
        'interpretation_api_healthy': is_healthy,
        'status': 'ok' if is_healthy else 'service_unavailable',
    }, status=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)


# ============================================================================
# EXAMPLE 7: Gradual degradation - provide cached summary if service is down
# ============================================================================

def get_summary_with_fallback(portfolio_id, model_output, fallback_text=None):
    """
    Try to get interpretation summary, but use fallback if service is down.
    """
    try:
        return get_summary(model_output)
    except InterpretationServiceError:
        # Service is down - return a generic summary
        return {
            'summary': fallback_text or 'The portfolio has been modeled. Please contact support for detailed interpretation.',
            'interpretation_only': True,
            'source': 'fallback',
            'note': 'Interpretation service unavailable; showing fallback message',
        }


# ============================================================================
# EXAMPLE 8: Integration with Django model/database
# ============================================================================

"""
If you have a Django model to store interpretation results:

from django.db import models

class PortfolioInterpretation(models.Model):
    portfolio_id = models.CharField(max_length=100)
    summary = models.TextField()
    source = models.CharField(max_length=50)  # 'groq', 'fallback', etc.
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['portfolio_id', '-created_at']),
        ]


Then in your view:

def store_and_return_summary(request):
    portfolio_id = request.data['portfolio_id']
    model_output = request.data['model_output']
    
    result = get_summary(model_output)
    
    # Store in database for audit trail
    interpretation = PortfolioInterpretation.objects.create(
        portfolio_id=portfolio_id,
        summary=result['summary'],
        source=result['source'],
    )
    
    return Response({
        'interpretation_id': interpretation.id,
        'summary': result['summary'],
    })
"""

# ============================================================================
# URL Configuration Example
# ============================================================================

"""
In your urls.py, add:

from django.urls import path
from . import examples  # This file

urlpatterns = [
    # ... existing patterns ...
    
    # Interpretation API examples
    path('api/portfolio/<str:portfolio_id>/summary/',
         examples.get_portfolio_summary_view,
         name='portfolio-summary'),
    path('api/portfolio/question/',
         examples.ask_question_view,
         name='ask-portfolio-question'),
    path('api/health/interpretation/',
         examples.service_health_view,
         name='interpretation-health-check'),
]
"""
