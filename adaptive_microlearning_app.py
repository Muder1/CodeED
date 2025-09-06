import streamlit as st
import json
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict

DATA_FILE = Path('data_store.json')

DEFAULT_STORE = {
    'settings': {'daily_mins': 15.0},
    'lectures': [],
    'completed_courses': [],
    'streak': {'current': 0, 'last_date': None, 'minutes_today': 0.0, 'last_fatigue': 0.0},
    'recommended_sessions': [],
    'recommended_total': 0.0
}

SCALE = 10  # one decimal place support

# -------------------- Utilities --------------------
def load_store():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            return json.loads(json.dumps(DEFAULT_STORE))
    else:
        return json.loads(json.dumps(DEFAULT_STORE))

def save_store(store):
    DATA_FILE.write_text(json.dumps(store, indent=2))

def to_units(mins):
    return max(0, int(round(mins * SCALE)))

def from_units(u):
    return u / SCALE

def flatten_segments(lectures):
    items = []
    for li, lec in enumerate(lectures):
        for si, seg in enumerate(lec.get('segments', [])):
            items.append({
                'id': f'{li}-{si}',
                'lecture_index': li,
                'lecture_title': lec.get('title'),
                'topic': seg.get('topic'),
                'mins': float(seg.get('mins')),
                'difficulty': int(seg.get('difficulty', 3)),
                'order': int(seg.get('order', 1))
            })
    return items

def compute_fatigue(minutes_done, avg_difficulty):
    score = 0.007 * minutes_done + 0.02 * avg_difficulty
    return min(score, 1.0)

def update_streak(store, minutes_done):
    today_str = date.today().isoformat()
    daily_target = store['settings'].get('daily_mins', 15.0)
    streak = store.get('streak', {'current':0,'last_date':None,'minutes_today':0.0,'last_fatigue':0.0})
    if streak.get('last_date') != today_str:
        streak['minutes_today'] = minutes_done
        streak['current'] = (streak.get('current',0) + 1) if minutes_done >= daily_target else 0
        streak['last_date'] = today_str
    else:
        streak['minutes_today'] += minutes_done
        if streak['minutes_today'] >= daily_target and streak['minutes_today'] - minutes_done < daily_target:
            streak['current'] += 1
    store['streak'] = streak
    return streak

# -------------------- Recommendation --------------------
def recommend_segments(lectures, daily_mins, fatigue_score, completed_courses, selected_lectures=None):
    items = flatten_segments(lectures)
    if not items:
        return [], 0.0

    completed_set = {(c['lecture_title'], c['topic']) for c in completed_courses}
    items = [it for it in items if (it['lecture_title'], it['topic']) not in completed_set]

    if selected_lectures:
        items = [it for it in items if it['lecture_title'] in selected_lectures]

    if not items:
        return [], 0.0

    # Soft order-aware inclusion: only recommend higher-order if lower-order is present
    order_map = defaultdict(list)
    for it in items:
        order_map[it['lecture_title']].append(it)
    filtered_items = []
    for lec, segs in order_map.items():
        segs.sort(key=lambda x:x['order'])
        available_orders = {1}
        for s in segs:
            if s['order'] == 1 or s['order'] in available_orders:
                filtered_items.append(s)
                available_orders.add(s['order']+1)
    items = filtered_items

    if not items:
        return [], 0.0

    # Knapsack-style selection based on daily minutes and fatigue
    total_available_time = sum(it['mins'] for it in items)
    low_u = to_units(daily_mins*0.7)
    high_u = to_units(daily_mins*1.3)
    if fatigue_score>0.6:
        low_u=int(low_u*0.9); high_u=int(high_u*0.85)
    if fatigue_score>0.8:
        low_u=int(low_u*0.9); high_u=int(high_u*0.7)
    if from_units(low_u)>total_available_time:
        return items,total_available_time

    scaled = [{'u': to_units(it['mins']), **it} for it in items]
    cap=min(sum(it['u'] for it in scaled), high_u)
    dp=[-1]*(cap+1); dp[0]=-2
    for i,it in enumerate(scaled):
        w=it['u']
        if w<=0: continue
        for s in range(cap,w-1,-1):
            if dp[s]==-1 and dp[s-w]!=-1:
                dp[s]=i

    best=-1
    for s in range(low_u,cap+1):
        if dp[s]!=-1: best=s
    if best==-1:
        for s in range(low_u-1,-1,-1):
            if dp[s]!=-1: best=s; break
        if best==-1:
            for s in range(low_u+1,cap+1):
                if dp[s]!=-1: best=s; break
    if best<=0: return [],0.0

    chosen_indices=set(); cur=best
    while cur>0:
        i=dp[cur]
        if i in chosen_indices: break
        chosen_indices.add(i)
        cur-=scaled[i]['u']

    chosen=[{'lecture_title':scaled[i]['lecture_title'],
             'topic':scaled[i]['topic'],
             'mins':scaled[i]['mins'],
             'difficulty':scaled[i].get('difficulty',3),
             'order':scaled[i].get('order',1)} for i in chosen_indices]

    return chosen, sum(c['mins'] for c in chosen)

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title='Adaptive Micro-Learning', layout='wide')
st.title('Adaptive Micro-Learning — Fatigue & Soft-Order Aware')

store = load_store()

# Patch old data
for lec in store.get('lectures',[]):
    for seg in lec.get('segments',[]):
        if 'difficulty' not in seg: seg['difficulty']=3
        if 'order' not in seg: seg['order']=1
for key in ['completed_courses','recommended_sessions']:
    if key not in store: store[key]=[]
if 'recommended_total' not in store: store['recommended_total']=0.0
if 'streak' not in store:
    store['streak']={'current':0,'last_date':None,'minutes_today':0.0,'last_fatigue':0.0}
save_store(store)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header('Settings')
    daily = st.number_input('Minimum minutes per day', min_value=1.0, value=float(store['settings'].get('daily_mins',15.0)), step=0.5)
    if st.button('Save settings'):
        store['settings']['daily_mins']=float(daily)
        save_store(store)
        st.success('Saved')

    st.markdown('---')
    st.header('Streak')
    st.write(f"Current streak: **{store['streak'].get('current',0)}**")
    st.write(f"Last active: **{store['streak'].get('last_date','—')}**")
    st.write(f"Minutes today: **{store['streak'].get('minutes_today',0.0)}**")
    st.write(f"Last fatigue: **{store['streak'].get('last_fatigue',0.0):.2f}**")

    st.markdown('---')
    st.header('Quick Actions')
    if st.button("Reset Completed Courses"):
        store['completed_courses']=[]
        store['streak']['minutes_today']=0.0
        store['streak']['last_fatigue']=0.0
        save_store(store)
        st.success("✅ Completed courses reset.")
        st.rerun()
    if st.button("Reset All Data"):
        store = json.loads(json.dumps(DEFAULT_STORE))
        save_store(store)
        st.success("✅ All data reset.")
        st.rerun()
    if st.button("Reset Streak"):
        store['streak']={'current':0,'last_date':None,'minutes_today':0.0,'last_fatigue':0.0}
        save_store(store)
        st.success("✅ Streak reset.")
        st.rerun()

# ---------------- Tabs ----------------
tab1,tab2=st.tabs(["📚 Learning","✅ Completed Courses"])

with tab1:
    col1,col2 = st.columns([2,3])
    # --- LEFT: Lectures ---
    with col1:
        st.subheader('Lectures & Segments')
        if store['lectures']:
            st.markdown("### Existing Lectures")
            for li,lec in enumerate(store['lectures']):
                with st.expander(f"📖 {lec['title']} — {sum(s['mins'] for s in lec.get('segments',[]))} min"):
                    for seg in lec.get('segments',[]):
                        st.write(f"- {seg['topic']} ({seg['mins']} min, Diff {seg.get('difficulty',3)}, Order {seg.get('order',1)})")
                    if st.button(f"❌ Delete Lecture", key=f"del_lec_{li}"):
                        store['lectures'].pop(li)
                        save_store(store)
                        st.rerun()
        else:
            st.info("No lectures yet. Add one below.")

        st.markdown('---')
        with st.expander('Add new lecture'):
            new_title=st.text_input('Lecture title', key='new_title')
            seg_topic=st.text_input('Segment topic', key='seg_topic')
            seg_mins=st.number_input('Minutes', min_value=0.5,value=5.0,step=0.5,key='seg_mins')
            seg_diff=st.slider('Difficulty',1,5,3,key='seg_difficulty')
            seg_order=st.number_input('Order',min_value=1,value=1,step=1,key='seg_order')
            if 'buffer_segments' not in st.session_state: st.session_state['buffer_segments']=[]
            if st.button('Add segment to buffer'):
                if not new_title: st.warning("Enter title first")
                else:
                    st.session_state['buffer_segments'].append({'topic':seg_topic,'mins':seg_mins,'difficulty':seg_diff,'order':seg_order})
                    st.rerun()
            if st.session_state.get('buffer_segments'):
                st.write('Buffered segments for:', new_title)
                for idx,s in enumerate(st.session_state['buffer_segments']):
                    st.write(f"{idx+1}. {s['topic']} — {s['mins']} min — Diff {s['difficulty']} — Order {s['order']}")
                    if st.button(f'Remove {idx}',key=f'remove_{idx}'):
                        st.session_state['buffer_segments'].pop(idx)
                        st.rerun()
            if st.button('Create lecture'):
                if not new_title or not st.session_state.get('buffer_segments'):
                    st.warning('Need title and at least one buffered segment')
                else:
                    store['lectures'].append({'title':new_title,'segments':st.session_state['buffer_segments']})
                    st.session_state['buffer_segments']=[]
                    save_store(store)
                    st.success('Lecture created')
                    st.rerun()

    # --- RIGHT: Recommendation & Session ---
    with col2:
        st.subheader('Recommendation & Session')
        main_lectures=[lec['title'] for lec in store['lectures']]
        selected_lectures=st.multiselect('Select lectures to recommend sessions from', main_lectures)

        if st.button('Recommend Sessions'):
            if not selected_lectures: st.warning("Select at least one lecture")
            else:
                chosen,total = recommend_segments(store['lectures'], store['settings']['daily_mins'],
                                                  store['streak'].get('last_fatigue',0),
                                                  store.get('completed_courses',[]),
                                                  selected_lectures)
                store['recommended_sessions']=chosen
                store['recommended_total']=total
                save_store(store)
                st.success("✅ Recommended sessions ready.")

        # Display recommended sessions
        if store.get('recommended_sessions'):
            st.write('Recommended sessions:')
            grouped=defaultdict(list)
            for c in store['recommended_sessions']: grouped[c['lecture_title']].append(c)
            for lec_title,segs in grouped.items():
                st.markdown(f"### 📖 {lec_title}")
                segs.sort(key=lambda x:x.get('order',1))
                for s in segs:
                    st.write(f"- {s['topic']} ({s['mins']} min, Diff {s.get('difficulty',3)}, Order {s.get('order',1)})")
            st.write(f"**Total:** {store.get('recommended_total',0.0):.1f} min")

            if 'active_session' not in st.session_state: st.session_state['active_session']=None
            if st.session_state['active_session'] is None:
                if st.button('Start Recommended Session'):
                    sess={'segments':[{'lecture_title':c['lecture_title'],'topic':c['topic'],'mins':c['mins'],
                                       'difficulty':c.get('difficulty',3),'order':c.get('order',1),'done':False}
                                      for c in store['recommended_sessions']],
                          'started_at':datetime.utcnow().isoformat()}
                    st.session_state['active_session']=sess
                    st.rerun()
            else:
                st.write('Active session in progress')
                for idx,s in enumerate(st.session_state['active_session']['segments']):
                    chk=st.checkbox(f"{s['lecture_title']} — {s['topic']} ({s['mins']} min)", value=s['done'], key=f'sess_{idx}')
                    st.session_state['active_session']['segments'][idx]['done']=chk
                if st.button('Finish Session'):
                    completed_today=[s for s in st.session_state['active_session']['segments'] if s['done']]
                    if not completed_today: st.warning("No courses selected. Session not recorded.")
                    else:
                        store['completed_courses'].extend([{**s,'completed_on':date.today().isoformat()} for s in completed_today])
                        minutes_done=sum(s['mins'] for s in completed_today)
                        avg_diff=sum(s.get('difficulty',3) for s in completed_today)/len(completed_today)
                        new_fatigue=store['streak'].get('last_fatigue',0)+compute_fatigue(minutes_done,avg_diff)
                        store['streak']=update_streak(store, minutes_done)
                        store['streak']['last_fatigue']=new_fatigue
                        remaining=[s for s in store['recommended_sessions']
                                   if (s['lecture_title'],s['topic']) not in {(c['lecture_title'],c['topic']) for c in completed_today}]
                        store['recommended_sessions']=remaining
                        store['recommended_total']=sum(s['mins'] for s in remaining)
                        st.session_state['active_session']=None
                        save_store(store)
                        st.success("✅ Session recorded.")

        # ---------------- Manual Add Section ----------------
        st.markdown("---")
        st.header("Manually Add Recommended Course")
        lecture_titles=[lec['title'] for lec in store['lectures']]
        selected_force_lecture=st.selectbox("Select lecture to force-add", ["--Select--"]+lecture_titles)
        if selected_force_lecture!="--Select--":
            lecture_obj=next(lec for lec in store['lectures'] if lec['title']==selected_force_lecture)
            segment_topics=[seg['topic'] for seg in lecture_obj.get('segments',[])]
            selected_force_segments=st.multiselect("Select segments to add to recommended", segment_topics)
            if st.button("Add to Recommended Sessions"):
                if not selected_force_segments:
                    st.warning("No segments selected. Nothing added.")
                else:
                    existing_set = {(s['lecture_title'], s['topic']) for s in store['recommended_sessions']}
                    added_count = 0
                    for seg in lecture_obj['segments']:
                        if seg['topic'] in selected_force_segments:
                            key = (selected_force_lecture, seg['topic'])
                            if key not in existing_set:
                                store['recommended_sessions'].append({
                                    'lecture_title': selected_force_lecture,
                                    'topic': seg['topic'],
                                    'mins': seg['mins'],
                                    'difficulty': seg.get('difficulty', 3),
                                    'order': seg.get('order', 1)
                                })
                                added_count += 1
                    if added_count > 0:
                        store['recommended_total'] = sum(s['mins'] for s in store['recommended_sessions'])
                        save_store(store)
                        st.success(f"{added_count} segment(s) added to recommended sessions.")
                        st.rerun()
                    else:
                        st.info("Selected segments are already in recommended sessions.")


with tab2:
    st.subheader("✅ Completed Courses (All-time)")
    if not store.get('completed_courses'): st.info("No courses completed yet.")
    else:
        for c in store['completed_courses']:
            st.write(f"**{c['lecture_title']}** — {c['topic']} | {c['mins']} min | Diff {c.get('difficulty',3)} | Order {c.get('order',1)} | Done on {c.get('completed_on','—')}")

save_store(store)
