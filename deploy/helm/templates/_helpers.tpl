{{- define "robinhood.labels" -}}
app.kubernetes.io/name: robinhood
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "robinhood.databaseEnv" -}}
- name: ROBINHOOD_DATABASE_SCHEMA
  value: {{ .Values.database.schema | quote }}
{{- end }}

{{- define "robinhood.podSecurity" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
fsGroupChangePolicy: OnRootMismatch
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "robinhood.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end }}
