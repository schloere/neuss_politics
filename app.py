import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
from collections import defaultdict
import time

# Konfiguration für mobile Ansicht
st.set_page_config(
    page_title="Neuss Ratsinformationssystem",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# CSS für bessere mobile Darstellung
st.markdown("""
    <style>
    .main {
        padding: 1rem;
    }
    table {
        font-size: 0.9rem;
    }
    @media (max-width: 768px) {
        .main {
            padding: 0.5rem;
        }
        table {
            font-size: 0.8rem;
        }
    }
    </style>
""", unsafe_allow_html=True)

# Basis-URLs
BASE_URL = "http://ris-oparl.itk-rheinland.de/Oparl/bodies/0009"
PEOPLE_URL = f"{BASE_URL}/people"
ORG_URL = f"{BASE_URL}/organizations"
PAPER_URL = f"{BASE_URL}/papers"

# Wahlperiode definieren
WAHLPERIODE_START = datetime(2025, 11, 1)
# Stichtag: Mitgliedschaften die vor diesem Datum enden, werden ausgefiltert
CUTOFF_DATE = datetime(2026, 1, 31)

@st.cache_data(ttl=3600)
def fetch_all_pages(base_url, max_pages=200):
    """
    Holt alle Seiten einer OParl-Liste durch Folgen der 'next'-Links.
    """
    all_data = []
    current_url = base_url
    page_count = 0
    
    while current_url and page_count < max_pages:
        page_count += 1
        
        try:
            response = requests.get(current_url, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Daten sammeln
            if 'data' in data:
                all_data.extend(data['data'])
            
            # Nächste Seite via 'next'-Link
            links = data.get('links', {})
            next_url = links.get('next')
            
            if not next_url:
                break
            
            current_url = next_url
            time.sleep(0.05)
            
        except Exception as e:
            st.warning(f"Fehler beim Abrufen von Seite {page_count} ({base_url}): {e}")
            break
    
    return all_data

@st.cache_data(ttl=3600)
def fetch_single_object(url):
    """Holt ein einzelnes Objekt"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return None

def normalize_gender(gender):
    """Normalisiert Geschlechtsangaben"""
    if not gender or gender == "":
        return "Divers"
    elif gender.lower() in ["männlich", "male", "m"]:
        return "Männlich"
    elif gender.lower() in ["weiblich", "female", "w", "f"]:
        return "Weiblich"
    else:
        return "Divers"

def is_in_current_period(membership):
    """
    Prüft ob Mitgliedschaft aktuell aktiv ist.
    NEUE LOGIK: Eine Mitgliedschaft ist aktiv wenn sie NICHT vor dem 31.01.2026 beendet wurde.
    """
    end_date_str = membership.get('endDate')
    
    # Kein Enddatum = Mitgliedschaft ist aktiv
    if not end_date_str:
        return True
    
    try:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
        # Mitgliedschaft ist nur aktiv, wenn sie nach dem Cutoff-Datum endet
        return end_date > CUTOFF_DATE
    except:
        return False

def get_party_from_memberships(person, org_dict):
    """Ermittelt die Partei/Fraktion einer Person"""
    memberships = person.get('membership', [])
    
    for membership_ref in memberships:
        if isinstance(membership_ref, str):
            membership = fetch_single_object(membership_ref)
        else:
            membership = membership_ref
        
        if not membership or not is_in_current_period(membership):
            continue
        
        org_id = membership.get('organization')
        if not org_id or org_id not in org_dict:
            continue
        
        org = org_dict[org_id]
        org_type = org.get('organizationType', '').lower()
        
        # Suche nach Fraktion oder Partei
        if 'fraktion' in org_type or 'partei' in org_type:
            return org.get('name', 'Unbekannt')
    
    return None

def main():
    st.title("🏛️ Ratsinformationssystem Neuss")
    st.subheader("Wahlperiode 2025-2030")
    
    # Info-Box
    with st.expander("ℹ️ Filter-Information"):
        st.info(f"""
        **Aktive Mitgliedschaften:**
        - Alle Mitgliedschaften ohne Enddatum
        - Alle Mitgliedschaften mit Enddatum nach {CUTOFF_DATE.strftime('%d.%m.%Y')}
        
        **Wahlperiode:** Ab {WAHLPERIODE_START.strftime('%d.%m.%Y')}
        """)
    
    # Daten laden
    with st.spinner("Lade Daten von der OParl-API..."):
        progress_text = st.empty()
        
        progress_text.text("📥 Lade Personen...")
        people_data = fetch_all_pages(PEOPLE_URL)
        
        progress_text.text("📥 Lade Gremien...")
        organizations_data = fetch_all_pages(ORG_URL)
        
        progress_text.text("📥 Lade Drucksachen (kann länger dauern)...")
        papers_data = fetch_all_pages(PAPER_URL, max_pages=500)
        
        progress_text.empty()
    
    # Deduplizierung
    unique_people = {}
    for person in people_data:
        person_id = person.get('id')
        if person_id:
            unique_people[person_id] = person
    people_data = list(unique_people.values())
    
    st.success(f"✅ {len(people_data)} Personen, {len(organizations_data)} Gremien, {len(papers_data)} Drucksachen geladen")
    
    # Organisationen in Dictionary
    org_dict = {org['id']: org for org in organizations_data}
    
    # Personen verarbeiten
    people_list = []
    gender_count = {"Männlich": 0, "Weiblich": 0, "Divers": 0}
    org_gender_count = defaultdict(lambda: {"Männlich": 0, "Weiblich": 0, "Divers": 0})
    person_counted = set()
    missing_orgs = set()
    person_party_map = {}  # Person ID -> Partei/Fraktion
    
    for person in people_data:
        gender = normalize_gender(person.get('gender', ''))
        person_name = person.get('name', 'Unbekannt')
        person_id = person.get('id', '')
        
        # Partei ermitteln
        party = get_party_from_memberships(person, org_dict)
        if party:
            person_party_map[person_id] = party
        
        memberships = person.get('membership', [])
        has_current_membership = False
        
        for membership_ref in memberships:
            if isinstance(membership_ref, str):
                membership = fetch_single_object(membership_ref)
            else:
                membership = membership_ref
            
            if not membership or not is_in_current_period(membership):
                continue
            
            has_current_membership = True
            
            org_id = membership.get('organization')
            if not org_id:
                continue
            
            if org_id not in org_dict:
                missing_orgs.add(org_id)
                org_name = f"⚠️ Gremium nicht in OParl (ID: .../{org_id.split('/')[-1]})"
            else:
                organization = org_dict[org_id]
                org_name = organization.get('name', 'Unbekannt')
            
            role = membership.get('role', '-')
            voting_right = "Ja" if membership.get('votingRight', False) else "Nein"
            start_date = membership.get('startDate', '-')
            end_date = membership.get('endDate', 'Aktiv')
            
            people_list.append({
                'Name': person_name,
                'Geschlecht': gender,
                'Partei/Fraktion': party if party else '-',
                'Ausschuss': org_name,
                'Rolle': role,
                'Stimmrecht': voting_right,
                'Von': start_date,
                'Bis': end_date
            })
            
            org_gender_count[org_name][gender] += 1
        
        if has_current_membership and person_id not in person_counted:
            gender_count[gender] += 1
            person_counted.add(person_id)
    
    # Drucksachen analysieren (Anträge/Anfragen)
    paper_stats = defaultdict(lambda: {'Anträge': 0, 'Anfragen': 0, 'Sonstige': 0})
    
    for paper in papers_data:
        # Nur Drucksachen aus aktueller Wahlperiode
        date_str = paper.get('date')
        if date_str:
            try:
                paper_date = datetime.strptime(date_str, '%Y-%m-%d')
                if paper_date < WAHLPERIODE_START:
                    continue
            except:
                pass
        
        paper_type = paper.get('paperType', '').lower()
        originators = paper.get('originatorPerson', []) + paper.get('originatorOrganization', [])
        
        # Typ kategorisieren
        if 'antrag' in paper_type:
            category = 'Anträge'
        elif 'anfrage' in paper_type:
            category = 'Anfragen'
        else:
            category = 'Sonstige'
        
        # Urheber zuordnen
        for originator_id in originators:
            # Prüfe ob Person
            if originator_id in person_party_map:
                party = person_party_map[originator_id]
                paper_stats[party][category] += 1
            # Prüfe ob Organisation
            elif originator_id in org_dict:
                org = org_dict[originator_id]
                org_name = org.get('name', 'Unbekannt')
                paper_stats[org_name][category] += 1
    
    # Tab-Navigation
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "👥 Personen", 
        "🏢 Ausschüsse", 
        "📊 Geschlechterverteilung",
        "📈 Ausschuss-Analyse",
        "📄 Anträge & Anfragen"
    ])
    
    # Tab 1: Personenliste
    with tab1:
        st.header("Personen im Rat")
        
        if people_list:
            df_people = pd.DataFrame(people_list)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                gender_filter = st.multiselect(
                    "Geschlecht:",
                    options=["Männlich", "Weiblich", "Divers"],
                    default=["Männlich", "Weiblich", "Divers"]
                )
            with col2:
                parties = sorted(df_people['Partei/Fraktion'].unique())
                party_filter = st.multiselect(
                    "Partei/Fraktion:",
                    options=parties,
                    default=[]
                )
            with col3:
                orgs = sorted(df_people['Ausschuss'].unique())
                org_filter = st.multiselect(
                    "Ausschuss:",
                    options=orgs,
                    default=[]
                )
            
            filtered_df = df_people[df_people['Geschlecht'].isin(gender_filter)]
            if party_filter:
                filtered_df = filtered_df[filtered_df['Partei/Fraktion'].isin(party_filter)]
            if org_filter:
                filtered_df = filtered_df[filtered_df['Ausschuss'].isin(org_filter)]
            
            sort_by = st.selectbox("Sortieren nach:", ["Name", "Partei/Fraktion", "Ausschuss", "Geschlecht"])
            filtered_df = filtered_df.sort_values(sort_by)
            
            st.dataframe(filtered_df, use_container_width=True, hide_index=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Anzahl Einträge", len(filtered_df))
            with col2:
                st.metric("Einzigartige Personen", filtered_df['Name'].nunique())
        else:
            st.info("Keine Personen gefunden.")
    
    # Tab 2: Ausschussliste
    with tab2:
        st.header("Ausschüsse")
        
        active_orgs = [org for org in organizations_data if org.get('name') in org_gender_count]
        
        if active_orgs or missing_orgs:
            org_list = []
            
            for org in active_orgs:
                org_name = org.get('name', 'Unbekannt')
                org_type = org.get('organizationType', '-')
                classification = org.get('classification', '-')
                total_members = sum(org_gender_count[org_name].values())
                
                org_list.append({
                    'Name': org_name,
                    'Typ': org_type,
                    'Klassifikation': classification,
                    'Status': '✅ In OParl',
                    'Mitglieder': total_members,
                    'Männlich': org_gender_count[org_name]['Männlich'],
                    'Weiblich': org_gender_count[org_name]['Weiblich'],
                    'Divers': org_gender_count[org_name]['Divers']
                })
            
            for org_name in org_gender_count.keys():
                if org_name.startswith('⚠️'):
                    total_members = sum(org_gender_count[org_name].values())
                    org_list.append({
                        'Name': org_name,
                        'Typ': 'Unbekannt',
                        'Klassifikation': 'Unbekannt',
                        'Status': '⚠️ Fehlt',
                        'Mitglieder': total_members,
                        'Männlich': org_gender_count[org_name]['Männlich'],
                        'Weiblich': org_gender_count[org_name]['Weiblich'],
                        'Divers': org_gender_count[org_name]['Divers']
                    })
            
            df_orgs = pd.DataFrame(org_list)
            df_orgs = df_orgs.sort_values('Mitglieder', ascending=False)
            
            st.dataframe(df_orgs, use_container_width=True, hide_index=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Ausschüsse in OParl", len(active_orgs))
            with col2:
                st.metric("Fehlende Gremien", len(missing_orgs))
    
    # Tab 3: Geschlechterverteilung
    with tab3:
        st.header("Geschlechterverteilung gesamt")
        
        if any(gender_count.values()):
            fig_pie = px.pie(
                values=list(gender_count.values()),
                names=list(gender_count.keys()),
                title="Verteilung nach Geschlecht",
                color_discrete_map={
                    'Männlich': '#3498db',
                    'Weiblich': '#e74c3c',
                    'Divers': '#95a5a6'
                }
            )
            
            fig_pie.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie.update_layout(height=400, margin=dict(t=50, b=20, l=20, r=20))
            
            st.plotly_chart(fig_pie, use_container_width=True)
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Männlich", gender_count['Männlich'])
            with col2:
                st.metric("Weiblich", gender_count['Weiblich'])
            with col3:
                st.metric("Divers", gender_count['Divers'])
            with col4:
                total = sum(gender_count.values())
                st.metric("Gesamt", total)
    
    # Tab 4: Ausschuss-Analyse
    with tab4:
        st.header("Geschlechterverteilung nach Ausschuss")
        
        if org_gender_count:
            chart_data = []
            for org_name, counts in org_gender_count.items():
                if org_name.startswith('⚠️'):
                    continue
                total = sum(counts.values())
                chart_data.append({
                    'Ausschuss': org_name,
                    'Männlich': counts['Männlich'],
                    'Weiblich': counts['Weiblich'],
                    'Divers': counts['Divers'],
                    'Gesamt': total
                })
            
            if chart_data:
                df_chart = pd.DataFrame(chart_data)
                df_chart = df_chart.sort_values('Gesamt', ascending=False)
                
                fig_bar = go.Figure()
                fig_bar.add_trace(go.Bar(name='Männlich', x=df_chart['Ausschuss'], y=df_chart['Männlich'], marker_color='#3498db'))
                fig_bar.add_trace(go.Bar(name='Weiblich', x=df_chart['Ausschuss'], y=df_chart['Weiblich'], marker_color='#e74c3c'))
                fig_bar.add_trace(go.Bar(name='Divers', x=df_chart['Ausschuss'], y=df_chart['Divers'], marker_color='#95a5a6'))
                
                fig_bar.update_layout(
                    title='Geschlechterverteilung pro Ausschuss',
                    xaxis_title='Ausschuss',
                    yaxis_title='Anzahl',
                    barmode='group',
                    height=500,
                    xaxis_tickangle=-45,
                    margin=dict(b=150)
                )
                
                st.plotly_chart(fig_bar, use_container_width=True)
                st.dataframe(df_chart, use_container_width=True, hide_index=True)
    
    # Tab 5: Anträge & Anfragen (NEU)
    with tab5:
        st.header("📄 Anträge & Anfragen nach Partei/Fraktion")
        
        st.info(f"""
        **Zeitraum:** Drucksachen ab {WAHLPERIODE_START.strftime('%d.%m.%Y')}
        
        **Hinweis:** Abstimmungsergebnisse sind in der OParl-API von Neuss leider nicht verfügbar.
        Die meisten Ratsinformationssysteme speichern nur Gesamtergebnisse, keine individuellen Abstimmungen.
        """)
        
        if paper_stats:
            # Tabelle erstellen
            stats_list = []
            for party, counts in paper_stats.items():
                stats_list.append({
                    'Partei/Fraktion': party,
                    'Anträge': counts['Anträge'],
                    'Anfragen': counts['Anfragen'],
                    'Sonstige': counts['Sonstige'],
                    'Gesamt': counts['Anträge'] + counts['Anfragen'] + counts['Sonstige']
                })
            
            df_stats = pd.DataFrame(stats_list)
            df_stats = df_stats.sort_values('Gesamt', ascending=False)
            
            # Diagramm
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Anträge', x=df_stats['Partei/Fraktion'], y=df_stats['Anträge'], marker_color='#2ecc71'))
            fig.add_trace(go.Bar(name='Anfragen', x=df_stats['Partei/Fraktion'], y=df_stats['Anfragen'], marker_color='#3498db'))
            fig.add_trace(go.Bar(name='Sonstige', x=df_stats['Partei/Fraktion'], y=df_stats['Sonstige'], marker_color='#95a5a6'))
            
            fig.update_layout(
                title='Drucksachen nach Partei/Fraktion',
                xaxis_title='Partei/Fraktion',
                yaxis_title='Anzahl',
                barmode='stack',
                height=500,
                xaxis_tickangle=-45
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Detaillierte Statistik")
            st.dataframe(df_stats, use_container_width=True, hide_index=True)
        else:
            st.warning("Keine Drucksachen-Daten für die aktuelle Wahlperiode gefunden.")
    
    # Footer
    st.markdown("---")
    st.caption(f"""
    OParl-API Neuss (ITK Rheinland) | 
    Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')} | 
    {len(people_data)} Personen, {len(organizations_data)} Gremien, {len(papers_data)} Drucksachen
    """)

if __name__ == "__main__":
    main()
