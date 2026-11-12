"use client";

import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import timeGridPlugin from "@fullcalendar/timegrid";
import ptBrLocale from "@fullcalendar/core/locales/pt-br";
import type {
  DateSelectArg,
  DatesSetArg,
  EventClickArg,
  EventContentArg,
  EventDropArg,
  EventInput,
} from "@fullcalendar/core";
import type { DateClickArg, EventResizeDoneArg } from "@fullcalendar/interaction";
import type { ReactNode } from "react";

type AgendaFullCalendarViewProps = {
  businessHours: unknown;
  duracaoSlot: string;
  eventAllow: (dropInfo: { start: Date; end: Date | null }) => boolean;
  eventClick: (arg: EventClickArg) => void;
  eventContent: (arg: EventContentArg) => ReactNode;
  eventDrop: (arg: EventDropArg) => void;
  eventOverlap: (stillEvent: any, movingEvent: any) => boolean;
  eventResize: (arg: EventResizeDoneArg) => void;
  events: EventInput[];
  dateClick: (arg: DateClickArg) => void;
  datesSet: (arg: DatesSetArg) => void;
  select: (arg: DateSelectArg) => void;
  selectAllow: (selectInfo: { start: Date; end: Date | null }) => boolean;
  selectOverlap: (event: any) => boolean;
  slotLaneClassNames: unknown;
  slotLaneContent: unknown;
  slotLaneDidMount: unknown;
  slotMaxTime: string;
  slotMinTime: string;
};

export default function AgendaFullCalendarView({
  businessHours,
  dateClick,
  datesSet,
  duracaoSlot,
  eventAllow,
  eventClick,
  eventContent,
  eventDrop,
  eventOverlap,
  eventResize,
  events,
  select,
  selectAllow,
  selectOverlap,
  slotLaneClassNames,
  slotLaneContent,
  slotLaneDidMount,
  slotMaxTime,
  slotMinTime,
}: AgendaFullCalendarViewProps) {
  return (
    <FullCalendar
      plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin, listPlugin]}
      initialView="dayGridMonth"
      locales={[ptBrLocale]}
      locale="pt-br"
      buttonText={{ today: "Hoje", month: "Mes", week: "Semana", day: "Dia", list: "Lista" }}
      headerToolbar={{
        left: "prev,next today",
        center: "title",
        right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek",
      }}
      events={events}
      eventContent={eventContent}
      datesSet={datesSet}
      eventClick={eventClick}
      dateClick={dateClick}
      select={select}
      eventDrop={eventDrop}
      eventResize={eventResize}
      nowIndicator
      businessHours={businessHours as any}
      editable
      selectable
      eventStartEditable
      eventDurationEditable
      selectMirror
      selectAllow={selectAllow}
      eventAllow={eventAllow}
      eventOverlap={eventOverlap}
      selectOverlap={selectOverlap}
      allDaySlot={false}
      slotMinTime={slotMinTime}
      slotMaxTime={slotMaxTime}
      slotDuration={duracaoSlot}
      snapDuration={duracaoSlot}
      slotLabelInterval={duracaoSlot}
      slotLaneClassNames={slotLaneClassNames as any}
      slotLaneContent={slotLaneContent as any}
      slotLaneDidMount={slotLaneDidMount as any}
      height="auto"
      eventTimeFormat={{ hour: "2-digit", minute: "2-digit", hour12: false }}
      dayMaxEventRows={3}
      dayMaxEvents
      eventDisplay="block"
      eventClassNames="cursor-pointer overflow-hidden"
    />
  );
}
