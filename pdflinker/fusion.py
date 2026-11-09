"""Experimental rank fusion configuration shared by settings and matching."""
import math

MODEL_NAMES=('bge','bge_base','granite','mixedbread')
DEFAULT_MINIMUM_SCORE=50


def default_rrf():
    # Exact 1:1:1:9 ratios preserve the tested 8 1/3%, 8 1/3%,
    # 8 1/3%, 75% shares even in the settings editor's decimal controls.
    return dict(enabled=True,k=1,minimum_rank_score=.5,
                weights={name:9. if name=='mixedbread' else 1. for name in MODEL_NAMES})


def validate_rrf(config):
    weights={name:float(config['weights'][name]) for name in MODEL_NAMES}
    if any(not math.isfinite(v) or not 0<=v<=1000 for v in weights.values()) or sum(weights.values())<=0:
        raise ValueError('RRF weights must be non-negative, with at least one above zero.')
    k=int(config['k']);minimum=float(config['minimum_rank_score'])
    if k!=float(config['k']) or not 1<=k<=1000:raise ValueError('RRF k must be between 1 and 1000.')
    if not math.isfinite(minimum) or not 0<=minimum<=1:raise ValueError('RRF rank cutoff must be between 0 and 100.')
    return dict(enabled=bool(config['enabled']),k=k,minimum_rank_score=minimum,weights=weights)


def reciprocal_rank_scores(scores,config):
    """Weighted normalised RRF, with average ranks for exact ties."""
    weights=config['weights'];total=sum(weights.values());k=config['k']
    count=len(next(iter(scores.values())))
    result=[0.]*count
    for name in MODEL_NAMES:
        values=scores[name]
        ranks=[1+sum(v>x for v in values)+(sum(v==x for v in values)-1)/2 for x in values]
        result=[s+weights[name]/total*(k+1)/(k+r) for s,r in zip(result,ranks)]
    return result
