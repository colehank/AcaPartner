"""Explicit typed-block exclusion shared by every scientific evidence projection.

This is structural separation, not a classifier for review language. Scientific
methods and selection histories remain byte-for-byte values inside the result.
"""
import copy
from research_partner.storage.store import digest

REVIEW_BLOCKS=frozenset({'author_assessment','self_assessment','review','review_verdict','review_findings','validation_receipt','execution_log'})
SCOPE='Explicit author/review/execution blocks and fields, plus note/report root legacy validation/acceptance aliases, are excluded with path/hash records. Untyped prose and method/selection history are retained; workshop validation remains scientific QC. This is structural separation, not semantic scrubbing.'


def project(content, kind=None):
    excluded=[];fields=[]
    # Legacy note/report root containers are author checks, unlike workshop
    # validation=manifest.quality. Nested methods.validation stays scientific.
    root_exclusions=REVIEW_BLOCKS | ({'validation','acceptance'} if kind in {'note','report'} else set())
    def walk(value,path):
        if isinstance(value,dict):
            result={}
            for key,nested in value.items():
                target=path+'.'+key
                if path=='content' and key in root_exclusions:
                    fields.append({'path':target,'kind':key,'sha256':digest(nested)});continue
                if key=='blocks' and isinstance(nested,list):
                    result[key]=[]
                    for index,block in enumerate(nested):
                        blockpath=target+'.'+str(index)
                        if isinstance(block,dict) and block.get('kind') in REVIEW_BLOCKS:
                            excluded.append({'path':blockpath,'id':block.get('id'),'kind':block['kind'],'sha256':digest(block)})
                        else:result[key].append(walk(block,blockpath))
                else:result[key]=walk(nested,target)
            return result
        if isinstance(value,list):return [walk(item,path+'.'+str(i)) for i,item in enumerate(value)]
        return copy.deepcopy(value)
    return walk(content,'content'),{'typed_blocks':excluded,'typed_fields':fields,'scope':SCOPE}
