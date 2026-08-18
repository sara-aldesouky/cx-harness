"""Deterministic aggregation over immutable analytics snapshots."""
from __future__ import annotations
from collections import Counter,defaultdict
from decimal import Decimal
from math import sqrt
from statistics import median
from app.benchmark_analytics.contracts import FinalOutcome,ResponsibilityLayer
from app.benchmark_reporting.contracts import *

ZERO=Decimal("0"); ONE=Decimal("1")
def d(value): return Decimal(str(value))
def ratio(numerator,denominator): return d(numerator)/d(denominator) if denominator else None
def mean(values): return sum(values,ZERO)/d(len(values)) if values else None
def med(values): return d(median(values)) if values else None
def std(values):
    if not values:return None
    average=mean(values); return d(sqrt(float(sum((x-average)**2 for x in values)/d(len(values)))))
def percentile(values,p):
    if not values:return None
    ordered=sorted(values); position=(len(ordered)-1)*p; low=int(position); high=min(low+1,len(ordered)-1)
    return ordered[low]+(ordered[high]-ordered[low])*d(position-low)

def aggregate_metrics(metrics):
    groups=defaultdict(list)
    for item in metrics: groups[(item.metric_key,item.metric_version,item.evaluation_method.value,item.evaluator_name,item.evaluator_version)].append(item)
    result=[]
    for key,items in sorted(groups.items()):
        nums=[i.value_numeric for i in items if i.value_numeric is not None]
        bools=[i.value_boolean for i in items if i.value_boolean is not None]
        texts=[i.value_text for i in items if i.value_text is not None]
        norms=[i.normalized_score for i in items if i.normalized_score is not None]
        result.append(QualityMetricSummary(metric_key=key[0],metric_version=key[1],evaluation_method=key[2],evaluator_name=key[3],evaluator_version=key[4],count=len(items),
            mean=mean(nums),median=med(nums),minimum=min(nums) if nums else None,maximum=max(nums) if nums else None,standard_deviation=std(nums),normalized_average=mean(norms),
            true_count=sum(v is True for v in bools) if bools else None,false_count=sum(v is False for v in bools) if bools else None,true_rate=ratio(sum(v is True for v in bools),len(bools)) if bools else None,value_distribution=dict(sorted(Counter(texts).items()))))
    return tuple(result)

def _metric_by_conversation(snapshot,key):
    values={}
    for item in snapshot.metrics:
        if item.metric_key==key:
            value=item.normalized_score
            if value is None and item.value_boolean is not None:value=d(int(item.value_boolean))
            if value is None and item.value_numeric is not None:value=item.value_numeric
            if value is not None:values[item.conversation_result_id]=value
    return values

def segment_summaries(snapshot,attribute,contract):
    groups=defaultdict(list)
    for row in snapshot.conversations:
        value=getattr(row,attribute)
        if value is not None:groups[value].append(row)
    task=_metric_by_conversation(snapshot,"conversation_completion"); selection=_metric_by_conversation(snapshot,"tool_selection_match_rate")
    tools=defaultdict(list)
    for item in snapshot.tool_executions:tools[item.conversation_result_id].append(item)
    failures=defaultdict(list)
    for item in snapshot.failures:failures[item.conversation_result_id].append(item)
    output=[]
    for name,rows in sorted(groups.items()):
        ids={r.id for r in rows}; ts=[t for i in ids for t in tools[i]]; fs=[f for i in ids for f in failures[i]]
        affected=lambda category:sum(any(f.failure_category.value==category for f in failures[r.id]) for r in rows)
        responsible=lambda layer:sum(any(f.responsibility_layer.value==layer for f in failures[r.id]) for r in rows)
        costs=[r.estimated_cost for r in rows if r.estimated_cost is not None]
        output.append(contract(segment=name,case_count=len(rows),pass_rate=ratio(sum(r.passed for r in rows),len(rows)),
            task_completion_rate=mean([task[r.id] for r in rows if r.id in task]),tool_selection_accuracy=mean([selection[r.id] for r in rows if r.id in selection]),
            tool_success_rate=ratio(sum(t.execution_successful for t in ts),len(ts)),grounding_failure_rate=ratio(sum(r.grounding_failure_detected for r in rows),len(rows)),
            hallucination_rate=ratio(sum(r.hallucination_detected for r in rows),len(rows)),clarification_rate=ratio(sum(r.clarification_count>0 for r in rows),len(rows)),
            average_provider_turns=mean([d(r.provider_turn_count) for r in rows]),average_tool_calls=mean([d(r.tool_execution_count) for r in rows]),average_total_tokens=mean([d(r.total_tokens) for r in rows]),
            average_latency_ms=mean([r.total_latency_ms for r in rows]),average_estimated_cost=mean(costs) if len(costs)==len(rows) else None,
            model_failure_rate=ratio(responsible("model"),len(rows)),business_data_failure_rate=ratio(affected("business_data"),len(rows)),context_loss_rate=ratio(affected("context_loss"),len(rows))))
    return tuple(output)

def aggregate_tools(snapshot):
    grouped=defaultdict(list); expected=Counter()
    for tool in snapshot.tool_executions:
        grouped[tool.tool_name].append(tool)
        if tool.expected_tool:expected[tool.expected_tool]+=1
    names=sorted(set(grouped)|set(expected)); output=[]
    for name in names:
        items=grouped[name]; correct=sum(i.selection_correct for i in items); selected=len(items); expected_count=expected[name]
        latencies=[i.latency_ms for i in items]; failures=Counter(i.failure_code for i in items if i.failure_code)
        output.append(ToolPerformanceSummary(tool_name=name,expected_count=expected_count,selected_count=selected,correct_selection_count=correct,
            incorrect_selection_count=selected-correct,selection_precision=ratio(correct,selected),selection_recall=ratio(correct,expected_count),execution_attempts=selected,
            valid_argument_count=sum(i.arguments_valid for i in items),invalid_argument_count=sum(not i.arguments_valid for i in items),authorization_pass_count=sum(i.authorization_passed for i in items),
            successful_execution_count=sum(i.execution_successful for i in items),business_failure_count=sum(i.business_failure for i in items),runtime_failure_count=sum((not i.execution_successful and not i.business_failure) for i in items),
            average_latency_ms=mean(latencies),median_latency_ms=med(latencies),failure_code_distribution=dict(sorted(failures.items()))))
    return tuple(output)

def aggregate_failures(snapshot,attribute,contract):
    groups=defaultdict(list)
    for failure in snapshot.failures:groups[getattr(failure,attribute).value].append(failure)
    total=len(snapshot.conversations)
    return tuple(contract(**({"category":key} if attribute=="failure_category" else {"responsibility_layer":key}),event_count=len(items),affected_conversation_count=len({i.conversation_result_id for i in items}),affected_conversation_rate=ratio(len({i.conversation_result_id for i in items}),total) or ZERO) for key,items in sorted(groups.items()))

def aggregate_tokens(snapshot):
    rows=snapshot.conversations; totals=[r.total_tokens for r in rows]; passed=sum(r.passed for r in rows); successful=sum(r.final_outcome is FinalOutcome.PASSED for r in rows)
    return TokenUsageSummary(total_input_tokens=sum(r.input_tokens for r in rows),total_output_tokens=sum(r.output_tokens for r in rows),total_tokens=sum(totals),average_tokens_per_conversation=mean([d(x) for x in totals]),median_tokens_per_conversation=med(totals),minimum_tokens=min(totals) if totals else None,maximum_tokens=max(totals) if totals else None,standard_deviation=std([d(x) for x in totals]),input_to_output_ratio=ratio(sum(r.input_tokens for r in rows),sum(r.output_tokens for r in rows)),tokens_per_successful_conversation=ratio(sum(totals),successful),tokens_per_passed_case=ratio(sum(totals),passed))

def aggregate_latency(snapshot):
    rows=snapshot.conversations; values=[r.total_latency_ms for r in rows]; provider=[t.latency_ms for t in snapshot.provider_turns]; tools=[t.latency_ms for t in snapshot.tool_executions]
    starts=[r.started_at for r in rows]; ends=[r.completed_at for r in rows]
    wall=d((max(ends)-min(starts)).total_seconds()*1000) if starts else None
    return LatencySummary(wall_clock_duration_ms=wall,accumulated_provider_latency_ms=sum(provider,ZERO),accumulated_tool_latency_ms=sum(tools,ZERO),accumulated_conversation_latency_ms=sum(values,ZERO),average_conversation_latency_ms=mean(values),median_conversation_latency_ms=med(values),minimum_conversation_latency_ms=min(values) if values else None,maximum_conversation_latency_ms=max(values) if values else None,standard_deviation_ms=std(values),p50_ms=percentile(values,.50),p75_ms=percentile(values,.75),p90_ms=percentile(values,.90),p95_ms=percentile(values,.95),p99_ms=percentile(values,.99),average_provider_turn_latency_ms=mean(provider),average_tool_latency_ms=mean(tools))

def aggregate_context(snapshot,threshold=Decimal("0.9")):
    available=[t for t in snapshot.provider_turns if t.context_tokens_used is not None]; ratios=[t.context_utilization_ratio for t in available if t.context_utilization_ratio is not None]
    conv_max=defaultdict(list)
    for t in available:
        if t.context_utilization_ratio is not None:conv_max[t.conversation_result_id].append(t.context_utilization_ratio)
    boundaries=[(ZERO,Decimal(".25"),"0-25%"),(Decimal(".25"),Decimal(".5"),"25-50%"),(Decimal(".5"),Decimal(".75"),"50-75%"),(Decimal(".75"),Decimal(".9"),"75-90%"),(Decimal(".9"),ONE,"90-100%")]
    rows={r.id:r for r in snapshot.conversations}; failure_ids={(f.conversation_result_id,f.failure_category.value) for f in snapshot.failures}; buckets=[]
    for low,high,label in boundaries:
        ids=[cid for cid,vals in conv_max.items() if low <= max(vals) <= high and (max(vals)<high or high==ONE)]
        selected=[rows[cid] for cid in ids]
        buckets.append(ContextBucketSummary(bucket=label,conversation_count=len(ids),pass_rate=ratio(sum(r.passed for r in selected),len(ids)) or ZERO,average_latency_ms=mean([r.total_latency_ms for r in selected]) or ZERO,average_output_tokens=mean([d(r.output_tokens) for r in selected]) or ZERO,model_failure_rate=ratio(sum(any(f.conversation_result_id==cid and f.responsibility_layer is ResponsibilityLayer.MODEL for f in snapshot.failures) for cid in ids),len(ids)) or ZERO,context_loss_rate=ratio(sum((cid,"context_loss") in failure_ids for cid in ids),len(ids)) or ZERO))
    return ContextWindowSummary(total_context_tokens=sum(t.context_tokens_used for t in available) if available else None,average_context_tokens_per_turn=mean([d(t.context_tokens_used) for t in available]),maximum_context_tokens=max((t.context_tokens_used for t in available),default=None),average_utilization_ratio=mean(ratios),maximum_utilization_ratio=max(ratios,default=None),conversations_above_threshold=sum(max(vals)>=threshold for vals in conv_max.values()),threshold=threshold,buckets=tuple(buckets))

def aggregate_cost(snapshot):
    rows=snapshot.conversations; costs=[r.estimated_cost for r in rows if r.estimated_cost is not None]; currencies={r.currency_code for r in rows if r.currency_code}
    if not rows or len(costs)!=len(rows) or len(currencies)!=1:return CostSummary(available=False,currency_code=next(iter(currencies)) if len(currencies)==1 else None,total_estimated_cost=None,average_cost_per_conversation=None,median_cost=None,minimum_cost=None,maximum_cost=None,cost_per_passed_conversation=None,cost_per_completed_task=None,projected_cost_per_thousand_conversations=None,input_token_cost_contribution=None,output_token_cost_contribution=None,request_charge_contribution=None,missing_components=("complete_comparable_cost",))
    total=sum(costs,ZERO); passed=sum(r.passed for r in rows)
    pricing=snapshot.run.pricing_snapshot; unit=pricing.assumptions.get("pricing_unit","per_million"); divisor=d(1000 if unit=="per_thousand" else 1_000_000)
    input_part=d(sum(r.input_tokens for r in rows))*(pricing.input_cost_per_million_tokens or ZERO)/divisor; output_part=d(sum(r.output_tokens for r in rows))*(pricing.output_cost_per_million_tokens or ZERO)/divisor; request_part=d(len(snapshot.provider_turns))*(pricing.request_cost or ZERO)
    return CostSummary(available=True,currency_code=next(iter(currencies)),total_estimated_cost=total,average_cost_per_conversation=mean(costs),median_cost=med(costs),minimum_cost=min(costs),maximum_cost=max(costs),cost_per_passed_conversation=ratio(total,passed),cost_per_completed_task=ratio(total,passed),projected_cost_per_thousand_conversations=mean(costs)*d(1000),input_token_cost_contribution=input_part,output_token_cost_contribution=output_part,request_charge_contribution=request_part)

def aggregate_intent(snapshot):
    rows=[r for r in snapshot.conversations if r.expected_intent]; exact=sum(r.actual_intent==r.expected_intent for r in rows); confusion=Counter((r.expected_intent,r.actual_intent) for r in rows); by_intent=defaultdict(list)
    for row in rows:by_intent[row.expected_intent].append(row)
    per_intent={key:ratio(sum(r.actual_intent==key for r in values),len(values)) for key,values in sorted(by_intent.items())}
    return IntentAnalysisSummary(evaluated_count=len(rows),exact_match_count=exact,exact_match_accuracy=ratio(exact,len(rows)),missed_intent_count=sum(r.actual_intent is None for r in rows),unsupported_intent_count=sum(r.actual_intent is not None and r.actual_intent!=r.expected_intent for r in rows),per_intent_accuracy=per_intent,confusion=tuple(IntentConfusionRow(expected_intent=k[0],actual_intent=k[1],count=v) for k,v in sorted(confusion.items(),key=lambda x:(x[0][0],x[0][1] or ""))))

def aggregate_execution(snapshot):
    rows=snapshot.conversations; count=len(rows); successful=sum(t.execution_successful for t in snapshot.tool_executions)
    return RunExecutionSummary(total_provider_turns=sum(r.provider_turn_count for r in rows),average_provider_turns=ratio(sum(r.provider_turn_count for r in rows),count),total_tool_executions=len(snapshot.tool_executions),successful_tool_executions=successful,failed_tool_executions=len(snapshot.tool_executions)-successful,tool_execution_success_rate=ratio(successful,len(snapshot.tool_executions)),total_clarifications=sum(r.clarification_count for r in rows),average_clarifications=ratio(sum(r.clarification_count for r in rows),count))

def aggregate_reliability(snapshot):
    by_layer=defaultdict(set); by_category=defaultdict(set)
    for failure in snapshot.failures:
        by_layer[failure.responsibility_layer.value].add(failure.conversation_result_id); by_category[failure.failure_category.value].add(failure.conversation_result_id)
    infrastructure=set().union(*(by_layer[x] for x in ("provider","harness","evaluation_pipeline")))
    return ReliabilitySummary(conversations_with_model_failures=len(by_layer["model"]),conversations_with_business_data_failures=len(by_category["business_data"]),conversations_with_provider_failures=len(by_layer["provider"]),conversations_with_harness_failures=len(by_layer["harness"]),conversations_with_infrastructure_failures=len(infrastructure),conversations_with_security_failures=len(by_layer["security"]),conversations_with_evaluation_pipeline_failures=len(by_layer["evaluation_pipeline"]))

def aggregate_grounding(snapshot):
    metric=_metric_by_conversation(snapshot,"grounding_enforcement_rate"); values=list(metric.values()); passed=sum(v>=ONE for v in values)
    return GroundingSummary(evaluated_conversations=len(values),enforcement_pass_count=passed,enforcement_failure_count=len(values)-passed,grounding_pass_rate=ratio(passed,len(values)),grounding_failure_rate=ratio(len(values)-passed,len(values)))

def aggregate_hallucination(snapshot):
    count=sum(r.hallucination_detected for r in snapshot.conversations)
    return HallucinationSummary(conversations_with_stored_signal=count,hallucination_rate=ratio(count,len(snapshot.conversations)))

def aggregate_buckets(snapshot,kind):
    if kind=="customer_turns":
        definitions=((lambda r:r.customer_turn_count<=2,"1-2 turns"),(lambda r:3<=r.customer_turn_count<=4,"3-4 turns"),(lambda r:5<=r.customer_turn_count<=6,"5-6 turns"),(lambda r:r.customer_turn_count>=7,"7+ turns"))
    else:
        definitions=((lambda r:r.tool_execution_count==0,"0 tools"),(lambda r:r.tool_execution_count==1,"1 tool"),(lambda r:r.tool_execution_count==2,"2 tools"),(lambda r:3<=r.tool_execution_count<=4,"3-4 tools"),(lambda r:r.tool_execution_count>=5,"5+ tools"))
    continuity=_metric_by_conversation(snapshot,"continuity_resolution_rate"); failure_by_conv=defaultdict(list)
    for failure in snapshot.failures:failure_by_conv[failure.conversation_result_id].append(failure)
    output=[]
    for predicate,label in definitions:
        rows=[r for r in snapshot.conversations if predicate(r)]; count=len(rows); model=sum(any(f.responsibility_layer is ResponsibilityLayer.MODEL for f in failure_by_conv[r.id]) for r in rows)
        output.append(ConversationBucketSummary(bucket=label,conversation_count=count,pass_rate=ratio(sum(r.passed for r in rows),count) or ZERO,grounding_pass_rate=ratio(sum(not r.grounding_failure_detected for r in rows),count) or ZERO,context_retention_rate=mean([continuity[r.id] for r in rows if r.id in continuity]),average_tokens=mean([d(r.total_tokens) for r in rows]) or ZERO,average_latency_ms=mean([r.total_latency_ms for r in rows]) or ZERO,hallucination_rate=ratio(sum(r.hallucination_detected for r in rows),count) or ZERO,model_failure_rate=ratio(model,count) or ZERO))
    return tuple(output)
