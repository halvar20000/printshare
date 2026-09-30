// Model -> printer, material, quality, plate, supports … -> slice (spec sections 3 + 4).
import Ionicons from "@expo/vector-icons/Ionicons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import {
  Banner, Button, Divider, Field, PickerSheet, Row, Screen, Section, Segmented, Stepper, tap, type Choice,
} from "@/components/ui";
import type { JobOptions, Lane, ModelColors, ModelFile, Options, Printer, PrinterKind } from "@/lib/api";
import { loadLastPrinter, loadPrefs, saveLastPrinter, savePrefs, useApp } from "@/lib/app";
import { brandOf, comboWarnings, jobName, plateName, shortName } from "@/lib/format";
import { defaultSlots, fits, presetForLane, slots } from "@/lib/lanes";
import { useColors } from "@/lib/theme";

type Params = { link?: string; fileUri?: string; fileName?: string; edit?: string };
type Edit = { printer?: string; file?: string | null; options?: JobOptions; name?: string; slots?: Record<number, number> };
type Sheet = "printer" | "filament" | "process" | "plate" | "file" | null;

export default function Prepare() {
  const { api, t } = useApp();
  const c = useColors();
  const router = useRouter();
  const params = useLocalSearchParams<Params>();
  const edit = useMemo<Edit>(() => { try { return params.edit ? JSON.parse(params.edit) : {}; } catch { return {}; } }, [params.edit]);

  const [link, setLink] = useState<string | null>(params.link ?? null);
  const [name, setName] = useState<string>(params.fileName ?? edit.name ?? "");
  const [error, setError] = useState<string>("");
  const [listed, setListed] = useState<{ link: string; files: ModelFile[] } | null>(null);
  const files = listed && listed.link === link ? listed.files : null;  // null while loading
  const [file, setFile] = useState<string | null>(edit.file ?? null);
  const [printers, setPrinters] = useState<Printer[]>([]);
  const [kinds, setKinds] = useState<Record<string, PrinterKind | "offline">>({});
  const [lanesBy, setLanesBy] = useState<Record<string, Lane[]>>({});
  const [printer, setPrinter] = useState<string>("");
  const [opts, setOpts] = useState<Options | null>(null);
  const [filament, setFilament] = useState("");
  const [filamentManual, setFilamentManual] = useState(!!edit.options?.filament);
  const [process, setProcess] = useState("");
  const [plate, setPlate] = useState("");
  const [supports, setSupports] = useState("off");
  const [brim, setBrim] = useState("auto");
  const [infill, setInfill] = useState<number | null>(null);  // null = profile default
  const [walls, setWalls] = useState<number | null>(null);
  const [more, setMore] = useState(false);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [submitting, setSubmitting] = useState(false);
  const firstLoad = useRef(true);

  // 1. file from the phone -> upload to the server first
  useEffect(() => {
    if (!api || !params.fileUri || link) return;
    api.upload(params.fileUri, params.fileName || "model.stl")
      .then(u => { setLink(u.link); setName(u.name); })
      .catch(e => setError(e.message));
  }, [api, params.fileUri, params.fileName, link]);
  const uploading = !!params.fileUri && !link && !error;

  // 2. files of the model (MQ-02)
  useEffect(() => {
    if (!api || !link) return;
    api.files(link).then(fl => {
      setListed({ link, files: fl });
      if (fl.length === 1) setFile(null);
      else if (!edit.file) {
        const threeMf = fl.filter(f => /\.3mf$/i.test(f.name));
        setFile(threeMf.length === 1 ? String(threeMf[0].index) : null);
      }
    }).catch(e => { setListed({ link, files: [] }); setError(e.message); });
  }, [api, link, edit.file]);

  // 2b. colours of a 3MF project (MA-04): one material per colour
  const fileName = files?.length === 1 ? files[0].name : files?.find(f => String(f.index) === file)?.name ?? null;
  const colorKey = link && fileName && /\.3mf$/i.test(fileName) ? `${link}|${files!.length > 1 ? file : ""}` : null;
  const [colorInfo, setColorInfo] = useState<{ key: string; data: ModelColors | null } | null>(null);
  const [perColor, setPerColor] = useState<Record<number, string>>({});
  const [colorSheet, setColorSheet] = useState<number | null>(null);
  useEffect(() => {
    if (!api || !colorKey || !link) return;
    let alive = true;
    api.inspect(link, files!.length > 1 ? file : null)
      .then(data => {
        if (!alive) return;
        setColorInfo({ key: colorKey, data });
        const saved = edit.options?.filaments;
        if (saved) setPerColor(Object.fromEntries(saved.map((f, i) => [i + 1, f]).filter(([, f]) => f)));
      })
      .catch(() => { if (alive) setColorInfo({ key: colorKey, data: null }); });   // single-colour flow
    return () => { alive = false; };
  }, [api, colorKey, link, file, files, edit.options?.filaments]);
  const colors = colorInfo?.key === colorKey ? colorInfo.data : null;
  const colorsLoading = !!colorKey && colorInfo?.key !== colorKey;
  const multi = !!colors && colors.filaments.length > 1 && colors.used.length > 1;

  // 3. printers + their state (DV-01)
  useEffect(() => {
    if (!api) return;
    (async () => {
      try {
        const list = await api.printers();
        setPrinters(list);
        const last = edit.printer ?? (await loadLastPrinter());
        setPrinter(list.find(p => p.id === last)?.id ?? list[0]?.id ?? "");
        list.forEach(p => api.status(p.id)
          .then(s => {
            setKinds(k => ({ ...k, [p.id]: s.kind }));
            setLanesBy(l => ({ ...l, [p.id]: s.lanes ?? [] }));
          })
          .catch(() => setKinds(k => ({ ...k, [p.id]: "offline" }))));
      } catch (e) {
        setError((e as Error).message);
      }
    })();
  }, [api, edit.printer]);

  // 4. presets for the chosen printer, preselected with the last choices (spec 4)
  const applyDefaults = useCallback((o: Options, keepDetails: JobOptions | null) => {
    const d = o.defaults;
    setSupports(keepDetails?.supports ?? d.supports);
    setBrim(keepDetails?.brim ?? d.brim);
    setInfill(keepDetails?.infill ?? null);
    setWalls(keepDetails?.walls ?? null);
  }, []);

  useEffect(() => {
    if (!api || !printer) return;
    let alive = true;
    (async () => {
      try {
        const useEdit = firstLoad.current && edit.options ? edit.options : null;
        const prefs = useEdit ?? (await loadPrefs(printer)) ?? {};
        let o = await api.options(printer);
        const wanted = prefs.process && o.processes.includes(prefs.process) ? prefs.process : o.defaults.process;
        if (wanted !== o.defaults.process) o = await api.options(printer, wanted);
        if (!alive) return;
        setOpts(o);
        setFilament(prefs.filament && o.materials.includes(prefs.filament) ? prefs.filament : o.defaults.filament);
        setProcess(o.defaults.process);
        setPlate(prefs.bed_type && o.plates.includes(prefs.bed_type) ? prefs.bed_type : o.defaults.bed_type);
        applyDefaults(o, useEdit);
        firstLoad.current = false;
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => { alive = false; };
  }, [api, printer, edit.options, applyDefaults]);

  const changeProcess = async (p: string) => {
    if (!api || !opts || p === process) return;
    setProcess(p);
    try {
      const o = await api.options(printer, p);
      setOpts(prev => (prev ? { ...prev, defaults: o.defaults } : o));
      applyDefaults(o, null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const d = opts?.defaults;
  const warnings = useMemo(() => (filament && plate ? comboWarnings(t, filament, plate) : []), [t, filament, plate]);
  // Slots (issue #12): printers with an AFC unit pick a slot per colour; the preset follows the slot
  const printerSlots = useMemo(() => slots(lanesBy[printer]), [lanesBy, printer]);
  const useSlots = printerSlots.length > 0;
  const modelColors = useMemo(() => (multi && colors
    ? colors.filaments.filter(f => colors.used.includes(f.index)).map(f => ({ index: f.index, color: f.color }))
    : [{ index: 1, color: colors?.filaments.length === 1 ? colors.filaments[0].color : null }]), [multi, colors]);
  const [slotChoice, setSlotChoice] = useState<Record<number, number>>(edit.slots ?? {});
  const [slotSheet, setSlotSheet] = useState<number | null>(null);
  const slotFor = useMemo(() => defaultSlots(modelColors, printerSlots, slotChoice),
    [modelColors, printerSlots, slotChoice]);
  const laneOf = (index: number) => printerSlots.find(l => l.tool === slotFor[index]);
  const presetFor = (index: number): string => {
    const manual = multi ? perColor[index] : filamentManual ? filament : undefined;
    if (manual) return manual;
    if (!useSlots) return filament;
    return presetForLane(laneOf(index), opts?.materials ?? [], filament, d?.filament ?? null) ?? filament;
  };
  const slotWarnings = useSlots ? modelColors.flatMap(mc => {
    const lane = laneOf(mc.index);
    if (!lane) return [];
    const what = multi ? t("colorN", { n: mc.index }) : t("lane");
    if (!lane.loaded) return [t("laneEmptyWarn", { what, lane: lane.slot })];
    const preset = presetFor(mc.index);
    return fits(preset, lane) ? [] : [t("laneMaterialWarn", { what, want: shortName(preset), lane: lane.slot, have: lane.material ?? "" })];
  }) : [];
  const needsFile = (files?.length ?? 0) > 1 && !file;
  const printerName = printers.find(p => p.id === printer)?.name ?? printer;

  const submit = async () => {
    if (!api || !link || !opts || !d) return;
    if (needsFile) { setError(t("chooseFile")); return; }
    const o: JobOptions = { process, bed_type: plate };
    const single = presetFor(1);
    if (!multi && single !== d.filament) o.filament = single;
    else if (multi && filament !== d.filament) o.filament = filament;
    if (multi && colors) {
      o.filaments = colors.filaments.map(f => (colors.used.includes(f.index) ? presetFor(f.index) : perColor[f.index] ?? null));
    }
    if (supports !== d.supports) o.supports = supports;
    if (brim !== d.brim) o.brim = brim;
    if (infill != null && infill !== d.infill) o.infill = infill;
    if (walls != null && walls !== d.walls) o.walls = walls;
    setSubmitting(true);
    setError("");
    try {
      await Promise.all([saveLastPrinter(printer),
        savePrefs(printer, { filament: multi ? filament : single, process, bed_type: plate })]);
      const { job } = await api.createJob(link, printer, file, o);
      // the chosen slots become the job screen's default (sent with /send, changeable without re-slicing)
      router.replace({ pathname: "/job/[id]", params: useSlots ? { id: job, slots: JSON.stringify(slotFor) } : { id: job } });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // ---------- choices for the picker sheets ----------
  const kindLabel = (id: string) => {
    const k = kinds[id];
    return k ? t.table.printerKinds[k] : undefined;
  };
  const choices: Record<Exclude<Sheet, null>, Choice[]> = {
    printer: printers.map(p => ({ value: p.id, label: p.name, sub: kindLabel(p.id) })),
    filament: (opts?.materials ?? []).map(m => ({ value: m, label: shortName(m),
      group: opts?.own?.materials.includes(m) ? t("ownProfiles") : brandOf(m) })),
    process: (opts?.processes ?? []).map(p => ({ value: p, label: shortName(p),
      group: opts?.own?.processes.includes(p) ? t("ownProfiles") : undefined })),
    plate: (opts?.plates ?? []).map(p => ({ value: p, label: plateName(t, p) })),
    file: (files ?? []).map(f => ({ value: String(f.index), label: f.name,
      sub: f.size ? `${(f.size / 1048576).toFixed(1)} MB` : undefined })),
  };
  const sheetValue: Record<Exclude<Sheet, null>, string | null> = { printer, filament: presetFor(1), process, plate, file };
  const sheetSet: Record<Exclude<Sheet, null>, (v: string) => void> = {
    printer: setPrinter, filament: v => { setFilament(v); setFilamentManual(true); }, process: changeProcess,
    plate: setPlate, file: setFile,
  };
  const sheetTitle: Record<Exclude<Sheet, null>, string> = {
    printer: t("printer"), filament: t("material"), process: t("quality"), plate: t("plate"), file: t("file"),
  };

  const dot = (id: string) => {
    const k = kinds[id];
    const color = !k ? c.sub : k === "offline" || k === "error" ? c.danger : k === "idle" || k === "done" || k === "stopped" ? c.ok : c.warn;
    return <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: color, marginLeft: 8 }} />;
  };

  if (uploading) {
    return (
      <View style={{ flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: c.bg }}>
        <ActivityIndicator size="large" color={c.accent} />
        <Text style={{ color: c.text, fontSize: 17, marginTop: 16 }}>{t("uploading")}</Text>
        {name ? <Text style={{ color: c.sub, marginTop: 6 }}>{name}</Text> : null}
      </View>
    );
  }

  const ready = !!(link && opts && files && printer);
  return (
    <Screen footer={
      <Button title={t("slice")} icon="layers-outline" onPress={submit} loading={submitting} disabled={!ready || needsFile} />
    }>
      {error ? <Banner kind="error" text={error} /> : null}

      <Section title={t("model")}>
        <Row icon="cube-outline" label={name || jobName(null, link)} sub={link && !link.startsWith("upload:") ? link : undefined} />
        {files === null && link ? (
          <><Divider /><Row label={t("filesLoading")} right={<ActivityIndicator color={c.accent} />} /></>
        ) : files && files.length > 1 ? (
          <><Divider />
            <Row icon="document-outline" label={file ? files.find(f => String(f.index) === file)?.name ?? t("file") : t("filesMany", { n: files.length })}
              onPress={() => setSheet("file")} />
          </>
        ) : files?.length === 1 && !name ? (
          <><Divider /><Row icon="document-outline" label={files[0].name} /></>
        ) : null}
      </Section>

      {printers.length === 0 && !error ? null : (
        <Section title={t("printer")}>
          <Row icon="print-outline" label={printerName || "…"} value={printer ? kindLabel(printer) : undefined}
            right={printer ? dot(printer) : null} onPress={printers.length > 1 ? () => setSheet("printer") : undefined} />
        </Section>
      )}

      {opts && d ? (
        <>
          {warnings.map(w => <Banner key={w} kind="warn" text={w} />)}
          {useSlots ? (
            <Section title={t("lanes")} footer={t("slotsHint")}>
              {modelColors.map((mc, i) => {
                const lane = laneOf(mc.index);
                return (
                  <View key={mc.index}>
                    {i ? <Divider /> : null}
                    <Row icon="file-tray-stacked-outline" label={multi ? t("colorN", { n: mc.index }) : t("lane")}
                      value={lane ? [lane.slot, lane.loaded ? lane.material : t("laneEmpty")].filter(Boolean).join(" · ") : "–"}
                      onPress={() => setSlotSheet(mc.index)}
                      right={<View style={{ flexDirection: "row", alignItems: "center", marginLeft: 8, gap: 4 }}>
                        {colorsLoading ? <ActivityIndicator color={c.accent} /> : null}
                        {multi && mc.color ? <View style={{ width: 14, height: 14, borderRadius: 7, backgroundColor: mc.color,
                          borderWidth: 1, borderColor: c.line }} /> : null}
                        <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: lane?.color || c.track,
                          borderWidth: 1, borderColor: c.line }} />
                      </View>} />
                    <Divider />
                    <Row icon="color-fill-outline" label={t("material")} value={shortName(presetFor(mc.index))}
                      onPress={() => (multi ? setColorSheet(mc.index) : setSheet("filament"))} />
                  </View>
                );
              })}
            </Section>
          ) : null}
          {useSlots ? slotWarnings.map(w => <Banner key={w} kind="warn" text={w} />) : null}
          {multi && colors && !useSlots ? (
            <Section title={t("colors")} footer={colors.painted ? t("colorsPainted") : t("colorsHint")}>
              {colors.filaments.filter(f => colors.used.includes(f.index)).map((f, i) => (
                <View key={f.index}>
                  {i ? <Divider /> : null}
                  <Row label={t("colorN", { n: f.index })} value={shortName(perColor[f.index] ?? filament)}
                    onPress={() => setColorSheet(f.index)}
                    right={<View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: f.color, marginLeft: 10,
                      borderWidth: 1, borderColor: c.line }} accessibilityLabel={f.color} />} />
                </View>
              ))}
            </Section>
          ) : null}
          <Section>
            {multi || useSlots ? null : <>
              <Row icon="color-fill-outline" label={t("material")} value={shortName(filament)} onPress={() => setSheet("filament")}
                right={colorsLoading ? <ActivityIndicator color={c.accent} style={{ marginLeft: 8 }} /> : null} />
              <Divider />
            </>}
            <Row icon="speedometer-outline" label={t("quality")} value={shortName(process)} onPress={() => setSheet("process")} />
            <Divider />
            <Row icon="grid-outline" label={t("plate")} value={plateName(t, plate)} onPress={() => setSheet("plate")} />
          </Section>

          <Section>
            <Field label={t("supports")}>
              <Segmented values={opts.supports} value={supports} onChange={setSupports}
                labels={{ off: t("supOff"), normal: t("supNormal"), tree: t("supTree") }} />
            </Field>
          </Section>

          <Pressable onPress={() => { tap(); setMore(m => !m); }} accessibilityRole="button"
            style={{ flexDirection: "row", alignItems: "center", paddingHorizontal: 16, marginBottom: 10 }}>
            <Text style={{ color: c.accent, fontSize: 16, flex: 1 }}>{t("more")}</Text>
            <Ionicons name={more ? "chevron-up" : "chevron-down"} size={18} color={c.accent} />
          </Pressable>
          {more ? (
            <Section>
              <Field label={t("brim")}>
                <Segmented values={opts.brims} value={brim} onChange={setBrim}
                  labels={{ auto: t("brimAuto"), off: t("brimOff"), outer: t("brimOuter") }} />
              </Field>
              <Divider />
              <Field label={t("infill")} hint={infill == null || infill === d.infill ? t("standard") : undefined}>
                <Stepper value={infill ?? d.infill ?? 15} min={0} max={100} step={5} onChange={setInfill} format={v => `${v} %`} />
              </Field>
              <Divider />
              <Field label={t("walls")} hint={walls == null || walls === d.walls ? t("standard") : undefined}>
                <Stepper value={walls ?? d.walls ?? 2} min={1} max={10} onChange={setWalls} />
              </Field>
            </Section>
          ) : null}
        </>
      ) : printer ? (
        <ActivityIndicator color={c.accent} style={{ marginTop: 24 }} />
      ) : null}

      {sheet ? (
        <PickerSheet visible title={sheetTitle[sheet]} choices={choices[sheet]} value={sheetValue[sheet]}
          onPick={sheetSet[sheet]} onClose={() => setSheet(null)} searchLabel={t("search")} closeLabel="OK" />
      ) : null}
      {slotSheet != null ? (
        <PickerSheet visible title={multi ? t("colorN", { n: slotSheet }) : t("lane")}
          choices={printerSlots.map(l => ({ value: String(l.tool),
            label: [l.slot, l.loaded ? l.material : t("laneEmpty")].filter(Boolean).join(" · "),
            sub: [l.filament, l.in_toolhead ? t("laneInToolhead") : null, `T${l.tool}`].filter(Boolean).join(" · ") }))}
          value={slotFor[slotSheet] != null ? String(slotFor[slotSheet]) : null}
          onPick={v => {
            setSlotChoice(p => ({ ...p, [slotSheet]: Number(v) }));
            // a new slot brings its own material: drop a material chosen by hand for this colour
            if (multi) setPerColor(({ [slotSheet]: _dropped, ...rest }) => rest);
            else setFilamentManual(false);
          }}
          onClose={() => setSlotSheet(null)} searchLabel={t("search")} closeLabel="OK" />
      ) : null}
      {colorSheet != null ? (
        <PickerSheet visible title={t("colorN", { n: colorSheet })} choices={choices.filament}
          value={presetFor(colorSheet)}
          onPick={v => setPerColor(p => ({ ...p, [colorSheet]: v }))} onClose={() => setColorSheet(null)}
          searchLabel={t("search")} closeLabel="OK" />
      ) : null}
    </Screen>
  );
}
