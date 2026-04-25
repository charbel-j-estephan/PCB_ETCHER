    #INCLUDE "P16F877A.INC"
    __CONFIG _CP_OFF & _WDT_OFF & _PWRTE_ON & _BODEN_OFF & _LVP_OFF & _HS_OSC
STEPS_PER_MM    EQU D'400'


REG1        EQU 0x21
REG2        EQU 0x22
REG3        EQU 0x23

RXBYTE      EQU 0x24
ENDFLAG     EQU 0x25



BUF         EQU 0x30


X5          EQU 0x3E
X4          EQU 0x3F
X3          EQU 0x40
X2          EQU 0x41
X1          EQU 0x42
X0          EQU 0x43
Y5          EQU 0x44
Y4          EQU 0x45
Y3          EQU 0x46
Y2          EQU 0x47
Y1          EQU 0x48
Y0          EQU 0x49
PENVAL      EQU 0x4A


XTGT_HI     EQU 0x50
XTGT_MD     EQU 0x51
XTGT_LO     EQU 0x52
YTGT_HI     EQU 0x53
YTGT_MD     EQU 0x54
YTGT_LO     EQU 0x55


XCUR_HI     EQU 0x56
XCUR_MD     EQU 0x57
XCUR_LO     EQU 0x58
YCUR_HI     EQU 0x59
YCUR_MD     EQU 0x5A
YCUR_LO     EQU 0x5B

DX_HI       EQU 0x5C
DX_MD       EQU 0x5D
DX_LO       EQU 0x5E
DY_HI       EQU 0x5F
DY_MD       EQU 0x60
DY_LO       EQU 0x61
BERR_HI     EQU 0x62
BERR_MD     EQU 0x63
BERR_LO     EQU 0x64
STEPX_HI    EQU 0x65
STEPX_MD    EQU 0x66
STEPX_LO    EQU 0x67
XDIR_F      EQU 0x68
YDIR_F      EQU 0x69
DOM_FLAG    EQU 0x6A

TMPH        EQU 0x6B
TMPL        EQU 0x6C
TMP2H       EQU 0x6D
TMP2L       EQU 0x6E
TMP3        EQU 0x6F


MULX        EQU 0x70
MULH        EQU 0x71
MULL        EQU 0x72


MUL_A       EQU 0x73
MUL_B_HI    EQU 0x74
MUL_B_LO    EQU 0x75
RES_HI      EQU 0x76
RES_LO      EQU 0x77
MUL_CNT     EQU 0x78

DLY1        EQU 0x79
DLY2        EQU 0x7A
DLY3        EQU 0x7B

#DEFINE X_STEP  PORTB,0
#DEFINE X_DIR   PORTB,1
#DEFINE Y_STEP  PORTB,2
#DEFINE Y_DIR   PORTB,3
#DEFINE SERVO   PORTB,4
#DEFINE LIM_X   PORTA,2
#DEFINE LIM_Y   PORTA,3

    ORG 0x00
    GOTO    INIT

INIT
    BSF     STATUS,RP0
    MOVLW   0x81
    MOVWF   TRISC
    MOVLW   B'00100100'
    MOVWF   TXSTA
    MOVLW   D'25'
    MOVWF   SPBRG
    CLRF    TRISD
    MOVLW   0x06
    MOVWF   ADCON1
    CLRF    TRISE
    CLRF    TRISB
    MOVLW   B'00001100'
    MOVWF   TRISA
    BCF     STATUS,RP0
    MOVLW   0x07
    MOVWF   CMCON
    CLRF    PORTE
    CLRF    PORTD
    MOVLW   B'10010000'
    MOVWF   RCSTA
    CLRF    PORTB
    CLRF    PORTA
    CLRF    ENDFLAG
    CLRF    PENVAL
    CLRF    XCUR_HI
    CLRF    XCUR_MD
    CLRF    XCUR_LO
    CLRF    YCUR_HI
    CLRF    YCUR_MD
    CLRF    YCUR_LO
    BTFSC   PIR1,RCIF
    MOVF    RCREG,W
    BTFSC   PIR1,RCIF
    MOVF    RCREG,W
    BCF     PIR1,RCIF
    CALL    CONFILCD

    CALL    HOME_AXES
    ; Display "MACHINE READY"
    MOVLW   H'01'
    CALL    COMMAND
    CALL    DELAY20MS
    MOVLW   H'84'
    CALL    COMMAND
    MOVLW   A'M'
    CALL    CHAR
    MOVLW   A'A'
    CALL    CHAR
    MOVLW   A'C'
    CALL    CHAR
    MOVLW   A'H'
    CALL    CHAR
    MOVLW   A'I'
    CALL    CHAR
    MOVLW   A'N'
    CALL    CHAR
    MOVLW   A'E'
    CALL    CHAR
    MOVLW   H'C5'
    CALL    COMMAND
    MOVLW   A'R'
    CALL    CHAR
    MOVLW   A'E'
    CALL    CHAR
    MOVLW   A'A'
    CALL    CHAR
    MOVLW   A'D'
    CALL    CHAR
    MOVLW   A'Y'
    CALL    CHAR

MAIN
    CALL    RECEIVE_LINE
    BTFSC   ENDFLAG,0
    GOTO    PLOT_DONE
    MOVLW   H'01'
    CALL    COMMAND
    CALL    DELAY20MS
    CALL    PARSE_AND_DISPLAY
    CALL    EXECUTE_MOTION
    CALL    SEND_ACK
    GOTO    MAIN

HOME_AXES
    MOVLW   H'01'
    CALL    COMMAND
    MOVLW   H'80'
    CALL    COMMAND
    MOVLW   A'H'
    CALL    CHAR
    MOVLW   A'O'
    CALL    CHAR
    MOVLW   A'M'
    CALL    CHAR
    MOVLW   A'I'
    CALL    CHAR
    MOVLW   A'N'
    CALL    CHAR
    MOVLW   A'G'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVLW   H'C0'
    CALL    COMMAND
    MOVLW   A'Y'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    BCF     Y_DIR
HOME_Y_LOOP
    BTFSS   LIM_Y
    GOTO    HOME_Y_DONE
    BSF     Y_STEP
    CALL    HOME_DELAY
    BCF     Y_STEP
    CALL    HOME_DELAY
    GOTO    HOME_Y_LOOP
HOME_Y_DONE
    CLRF    YCUR_HI
    CLRF    YCUR_MD
    CLRF    YCUR_LO
    MOVLW   H'C0'
    CALL    COMMAND
    MOVLW   A'X'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    BSF     X_DIR
HOME_X_LOOP
    BTFSS   LIM_X
    GOTO    HOME_X_DONE
    BSF     X_STEP
    CALL    HOME_DELAY
    BCF     X_STEP
    CALL    HOME_DELAY
    GOTO    HOME_X_LOOP
HOME_X_DONE
    CLRF    XCUR_HI
    CLRF    XCUR_MD
    CLRF    XCUR_LO
    RETURN


RECEIVE_LINE
    MOVLW   BUF
    MOVWF   FSR
    CLRF    ENDFLAG
RX_WAIT
    BTFSS   PIR1,RCIF
    GOTO    RX_WAIT
    MOVF    RCREG,W
    MOVWF   RXBYTE
    BCF     PIR1,RCIF
    BTFSC   RCSTA,OERR
    CALL    CLEAR_OERR

    MOVLW   0x0D
    SUBWF   RXBYTE,W
    BTFSC   STATUS,Z
    GOTO    RX_WAIT

    MOVLW   0x0A
    SUBWF   RXBYTE,W
    BTFSC   STATUS,Z
    GOTO    LINE_DONE

    MOVF    RXBYTE,W
    MOVWF   INDF
    INCF    FSR,F
    GOTO    RX_WAIT
LINE_DONE

    MOVLW   BUF+13
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   PENVAL

    MOVLW   BUF
    MOVWF   FSR
    MOVF    INDF,W
    SUBLW   A'E'
    BTFSS   STATUS,Z
    RETURN
    INCF    FSR,F
    MOVF    INDF,W
    SUBLW   A'N'
    BTFSS   STATUS,Z
    RETURN
    INCF    FSR,F
    MOVF    INDF,W
    SUBLW   A'D'
    BTFSS   STATUS,Z
    RETURN
    BSF     ENDFLAG,0
    RETURN
CLEAR_OERR
    BCF     RCSTA,CREN
    BSF     RCSTA,CREN
    RETURN

PARSE_AND_DISPLAY
    MOVLW   BUF+1
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X5
    MOVLW   BUF+2
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X4
    MOVLW   BUF+3
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X3
    MOVLW   BUF+4
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X2
    MOVLW   BUF+5
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X1
    MOVLW   BUF+6
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   X0
    MOVLW   BUF+7
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y5
    MOVLW   BUF+8
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y4
    MOVLW   BUF+9
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y3
    MOVLW   BUF+10
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y2
    MOVLW   BUF+11
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y1
    MOVLW   BUF+12
    MOVWF   FSR
    MOVF    INDF,W
    MOVWF   Y0

    ; LCD "X:NNN.N Y:NNN.N "
    CALL    CONV_X
    MOVLW   H'80'
    CALL    COMMAND
    MOVLW   A'X'
    CALL    CHAR
    MOVLW   A':'
    CALL    CHAR
    CALL    DISP_DIGITS
    MOVLW   A' '
    CALL    CHAR

    MOVLW   H'C0'
    CALL    COMMAND

    CALL    CONV_Y
    MOVLW   A'Y'
    CALL    CHAR
    MOVLW   A':'
    CALL    CHAR
    CALL    DISP_DIGITS
    MOVLW   A' '
    CALL    CHAR

    RETURN
; ===========================================================
;   DISP_DIGITS
;   Converts 24-bit step count in MULX:MULH:MULL to mm with
;   1 decimal place and outputs 5 LCD chars: "NNN.N"
;   (e.g. 80000 steps / 400 steps/mm = 200.0 -> "200.0")
;   Strategy: repeated subtraction of 40000 / 4000 / 400 / 40.
;   Save/restore on underflow so the remainder is always correct.
;   Clobbers: REG1, REG2, REG3, TMPH, TMPL, TMP2H, TMP2L, TMP3
;   MULX:MULH:MULL is consumed (left as remainder mod 40).
; ===========================================================
DISP_DIGITS
    ; --- Hundreds of mm: subtract 40000 = 0x009C40 ---
    CLRF    REG1
DD_H_LOOP
    MOVF    MULX,W
    MOVWF   TMP3            ; save HI
    MOVF    MULH,W
    MOVWF   TMPH            ; save MD
    MOVF    MULL,W
    MOVWF   TMPL            ; save LO
    MOVLW   0x40
    SUBWF   MULL,F          ; MULL -= 0x40; C=0 -> borrow
    MOVLW   0x9C
    BTFSS   STATUS,C
    ADDLW   1               ; add borrow: subtract 0x9D from MULH
    SUBWF   MULH,F          ; C=0 -> borrow
    MOVLW   0x00
    BTFSS   STATUS,C
    ADDLW   1               ; add borrow: subtract 1 from MULX
    SUBWF   MULX,F          ; C=0 -> overall underflow
    BTFSS   STATUS,C
    GOTO    DD_H_RESTORE
    INCF    REG1,F
    GOTO    DD_H_LOOP
DD_H_RESTORE
    MOVF    TMP3,W
    MOVWF   MULX
    MOVF    TMPH,W
    MOVWF   MULH
    MOVF    TMPL,W
    MOVWF   MULL
    ; --- Tens of mm: subtract 4000 = 0x000FA0 ---
    CLRF    REG2
DD_T_LOOP
    MOVF    MULX,W
    MOVWF   TMP3
    MOVF    MULH,W
    MOVWF   TMPH
    MOVF    MULL,W
    MOVWF   TMPL
    MOVLW   0xA0
    SUBWF   MULL,F
    MOVLW   0x0F
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULH,F
    MOVLW   0x00
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULX,F
    BTFSS   STATUS,C
    GOTO    DD_T_RESTORE
    INCF    REG2,F
    GOTO    DD_T_LOOP
DD_T_RESTORE
    MOVF    TMP3,W
    MOVWF   MULX
    MOVF    TMPH,W
    MOVWF   MULH
    MOVF    TMPL,W
    MOVWF   MULL
    ; --- Ones of mm: subtract 400 = 0x000190 ---
    CLRF    REG3
DD_O_LOOP
    MOVF    MULX,W
    MOVWF   TMP3
    MOVF    MULH,W
    MOVWF   TMPH
    MOVF    MULL,W
    MOVWF   TMPL
    MOVLW   0x90
    SUBWF   MULL,F
    MOVLW   0x01
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULH,F
    MOVLW   0x00
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULX,F
    BTFSS   STATUS,C
    GOTO    DD_O_RESTORE
    INCF    REG3,F
    GOTO    DD_O_LOOP
DD_O_RESTORE
    MOVF    TMP3,W
    MOVWF   MULX
    MOVF    TMPH,W
    MOVWF   MULH
    MOVF    TMPL,W
    MOVWF   MULL
    ; --- Tenths of mm: subtract 40 = 0x000028 ---
    ; Use TMPH as digit counter here (TMP3:TMP2H:TMP2L for save)
    CLRF    TMPH
DD_F_LOOP
    MOVF    MULX,W
    MOVWF   TMP3
    MOVF    MULH,W
    MOVWF   TMP2H
    MOVF    MULL,W
    MOVWF   TMP2L
    MOVLW   0x28
    SUBWF   MULL,F
    MOVLW   0x00
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULH,F
    MOVLW   0x00
    BTFSS   STATUS,C
    ADDLW   1
    SUBWF   MULX,F
    BTFSS   STATUS,C
    GOTO    DD_F_RESTORE
    INCF    TMPH,F
    GOTO    DD_F_LOOP
DD_F_RESTORE
    MOVF    TMP3,W
    MOVWF   MULX
    MOVF    TMP2H,W
    MOVWF   MULH
    MOVF    TMP2L,W
    MOVWF   MULL
    ; --- Output digits: REG1 REG2 REG3 . TMPH ---
    ; CHAR calls DELAY10MS which destroys REG1/REG2/REG3.
    ; Save all four digit values to registers DELAY10MS does NOT touch.
    MOVF    REG1,W
    MOVWF   TMP3        ; hundreds -> TMP3 (safe)
    MOVF    REG2,W
    MOVWF   TMP2H       ; tens    -> TMP2H (safe)
    MOVF    REG3,W
    MOVWF   TMP2L       ; ones    -> TMP2L (safe)
    ; TMPH = tenths (not touched by DELAY10MS, already safe)
    MOVF    TMP3,W
    ADDLW   A'0'
    CALL    CHAR
    MOVF    TMP2H,W
    ADDLW   A'0'
    CALL    CHAR
    MOVF    TMP2L,W
    ADDLW   A'0'
    CALL    CHAR
    MOVLW   A'.'
    CALL    CHAR
    MOVF    TMPH,W
    ADDLW   A'0'
    CALL    CHAR
    RETURN
; ===========================================================
;   EXECUTE_MOTION
;
;   SERVER sends:  '1' = pen DOWN (draw trace)
;                  '2' = pen UP   (travel / reposition)
;
;   SERVO_PULSE_DOWN  = 1ms HIGH = SG90 at 0�   = pen presses onto PCB
;   SERVO_PULSE_UP    = 2ms HIGH = SG90 at 180�  = pen lifts off  PCB
;
;   Servo is driven unconditionally on every command:
;     D'10' pulses � 20ms = 200ms � enough for full 180� travel.
;   No state-change detection needed: simple, reliable, easy to verify.
; ===========================================================
EXECUTE_MOTION
    CALL    CONV_X
    CALL    CONV_Y
    ; [DBG] Echo PENVAL over UART so we can see what the PIC received.
    ; Expected: 0x31 ('1') = pen DOWN, 0x32 ('2') = pen UP.
    ; 0x00 = RECEIVE_LINE never completed. Anything else = corruption.
    ; This byte appears on the terminal BEFORE the 'A' ACK.
DBG_TX_WAIT
    BTFSS   PIR1,TXIF           ; [DBG] wait for TX register empty
    GOTO    DBG_TX_WAIT         ; [DBG]
    MOVF    PENVAL,W            ; [DBG] load PENVAL
    MOVWF   TXREG               ; [DBG] transmit it � remove these 4 lines after diagnosis
    ; Drive servo for 10 pulses (200ms) � every command, no exceptions
    MOVLW   D'10'
    MOVWF   REG3
PEN_LOOP
    MOVLW   A'1'
    SUBWF   PENVAL,W            ; Z=1 if PENVAL='1' (pen DOWN)
    BTFSC   STATUS,Z
    CALL    SERVO_PULSE_DOWN    ; '1' ? 1ms (0deg) ? presses pen onto PCB
    MOVLW   A'2'
    SUBWF   PENVAL,W            ; Z=1 if PENVAL='2' (pen UP)
    BTFSC   STATUS,Z
    CALL    SERVO_PULSE_UP      ; '2' ? ~1.085ms ? lifts pen 15deg off PCB
    DECFSZ  REG3,F
    GOTO    PEN_LOOP
    CALL    BRESENHAM
    RETURN
; ===========================================================
;   SERVO PULSES � single 20ms PWM frame per call
; ===========================================================
SERVO_PULSE_UP
    ; myservo.write(15) equivalent: ~1.085ms HIGH = 15deg above 0deg
    ; Formula: 5*DLY1 + 5 = 1085us  ?  DLY1 = 216  (DLY2=1 outer loop)
    BSF     SERVO
    MOVLW   D'1'                ; 1 outer loop ? ~1.085ms HIGH (15deg, pen just off paper)
    MOVWF   DLY2
SPU_H_OUT
    MOVLW   D'216'              ; 5�216 + 5 = 1085 cycles � 1.085ms
    MOVWF   DLY1
SPU_H_IN
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    SPU_H_IN
    DECFSZ  DLY2,F
    GOTO    SPU_H_OUT
    BCF     SERVO
    MOVLW   D'19'               ; 19ms LOW ? total period ~20.2ms
    MOVWF   DLY2
SPU_L_OUT
    MOVLW   D'200'
    MOVWF   DLY1
SPU_L_IN
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    SPU_L_IN
    DECFSZ  DLY2,F
    GOTO    SPU_L_OUT
    RETURN
SERVO_PULSE_DOWN
    BSF     SERVO
    MOVLW   D'1'                ; 1ms HIGH
    MOVWF   DLY2
SPD_H_OUT
    MOVLW   D'200'
    MOVWF   DLY1
SPD_H_IN
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    SPD_H_IN
    DECFSZ  DLY2,F
    GOTO    SPD_H_OUT
    BCF     SERVO
    MOVLW   D'19'               ; 19ms LOW
    MOVWF   DLY2
SPD_L_OUT
    MOVLW   D'200'
    MOVWF   DLY1
SPD_L_IN
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    SPD_L_IN
    DECFSZ  DLY2,F
    GOTO    SPD_L_OUT
    RETURN
; ===========================================================
;   CONV_X
;   Converts 6 ASCII decimal digit step value (X5..X0) into
;   a 24-bit step count in XTGT_HI:XTGT_MD:XTGT_LO.
;   Formula (Horner): steps = ((((X5*10+X4)*10+X3)*10+X2)*10+X1)*10+X0
;   Uses 24-bit accumulator MULX:MULH:MULL and MUL10_24.
;   Server pre-multiplied by 400 � no further scaling needed.
; ===========================================================
CONV_X
    ; Seed accumulator with X5 digit value
    CLRF    MULX
    CLRF    MULH
    MOVF    X5,W
    ANDLW   0x0F
    MOVWF   MULL
    ; acc = acc*10 + X4
    CALL    MUL10_24
    MOVF    X4,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    ; acc = acc*10 + X3
    CALL    MUL10_24
    MOVF    X3,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    ; acc = acc*10 + X2
    CALL    MUL10_24
    MOVF    X2,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    ; acc = acc*10 + X1
    CALL    MUL10_24
    MOVF    X1,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    ; acc = acc*10 + X0
    CALL    MUL10_24
    MOVF    X0,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    ; Store 24-bit result into XTGT
    MOVF    MULX,W
    MOVWF   XTGT_HI
    MOVF    MULH,W
    MOVWF   XTGT_MD
    MOVF    MULL,W
    MOVWF   XTGT_LO
    RETURN
; ===========================================================
;   CONV_Y  (identical structure to CONV_X)
; ===========================================================
CONV_Y
    CLRF    MULX
    CLRF    MULH
    MOVF    Y5,W
    ANDLW   0x0F
    MOVWF   MULL
    CALL    MUL10_24
    MOVF    Y4,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    CALL    MUL10_24
    MOVF    Y3,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    CALL    MUL10_24
    MOVF    Y2,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    CALL    MUL10_24
    MOVF    Y1,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    CALL    MUL10_24
    MOVF    Y0,W
    ANDLW   0x0F
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F
    MOVF    MULX,W
    MOVWF   YTGT_HI
    MOVF    MULH,W
    MOVWF   YTGT_MD
    MOVF    MULL,W
    MOVWF   YTGT_LO
    RETURN
; ===========================================================
;   MUL10_24
;   Multiplies 24-bit accumulator MULX:MULH:MULL by 10.
;   Method: 10*X = 8*X + 2*X
;     1. Shift left once  -> 2*X (save in TMP3:TMPH:TMPL)
;     2. Shift left twice -> 8*X
;     3. Add back 2*X
;   Max input before final digit add: ~19999 = 0x04E1F  (safe in 3 bytes)
; ===========================================================
MUL10_24
    ; Step 1: shift left 1 to get 2*X
    BCF     STATUS,C
    RLF     MULL,F
    RLF     MULH,F
    RLF     MULX,F
    ; Save 2*X into TMP3:TMPH:TMPL
    MOVF    MULX,W
    MOVWF   TMP3
    MOVF    MULH,W
    MOVWF   TMPH
    MOVF    MULL,W
    MOVWF   TMPL
    ; Step 2: shift left 2 more to get 8*X
    BCF     STATUS,C
    RLF     MULL,F
    RLF     MULH,F
    RLF     MULX,F
    BCF     STATUS,C
    RLF     MULL,F
    RLF     MULH,F
    RLF     MULX,F
    ; Step 3: add 2*X back (MULX:MULH:MULL += TMP3:TMPH:TMPL)
    ; LO byte � carry from LO propagates into MULH via INCF
    MOVF    TMPL,W
    ADDWF   MULL,F
    BTFSC   STATUS,C
    INCF    MULH,F              ; carry from LO (MULH bounded, won't wrap)
    ; MD byte
    MOVF    TMPH,W
    ADDWF   MULH,F
    BTFSC   STATUS,C
    INCF    MULX,F              ; carry from MD
    ; HI byte
    MOVF    TMP3,W
    ADDWF   MULX,F
    RETURN
; ===========================================================
;   BRESENHAM
;   2D line algorithm. Dominant axis always steps once per
;   iteration. Minor axis steps when accumulated error
;   exceeds the dominant delta.
;
;   All arithmetic is 24-bit to handle up to 100000 steps.
;
;   XDIR_F = 1: X moving toward home (negative direction)
;   YDIR_F = 1: Y moving toward home (negative direction)
;   DOM_FLAG = 0: X dominant | DOM_FLAG = 1: Y dominant
;
;   [v10-FIX-8] 16-bit BERR >= DELTA comparisons correctly
;   propagate borrow � extended to 24-bit in v11.
;
;   [v10-FIX-9] DX and DY direction subtractions correctly
;   propagate borrow � extended to 24-bit in v11.
; ===========================================================
BRESENHAM
    ; Early exit if already at target (24-bit compare X then Y)
    MOVF    XTGT_LO,W
    SUBWF   XCUR_LO,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    MOVF    XTGT_MD,W
    SUBWF   XCUR_MD,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    MOVF    XTGT_HI,W
    SUBWF   XCUR_HI,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    MOVF    YTGT_LO,W
    SUBWF   YCUR_LO,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    MOVF    YTGT_MD,W
    SUBWF   YCUR_MD,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    MOVF    YTGT_HI,W
    SUBWF   YCUR_HI,W
    BTFSS   STATUS,Z
    GOTO    BRES_CALC
    RETURN                      ; Already at target

; --- Compute |DX| and X direction (24-bit, borrow-propagating) ---
; [v10-FIX-9 / v11] Pattern: load next subtrahend byte WITHOUT changing C,
; then conditionally add the borrow before performing the SUBWF.
BRES_CALC
    MOVF    XCUR_LO,W
    SUBWF   XTGT_LO,W           ; W = XTGT_LO - XCUR_LO, C=0 if borrow
    MOVWF   DX_LO
    MOVF    XCUR_MD,W            ; MOVF does NOT change C
    BTFSS   STATUS,C             ; C=0 (borrow) -> add 1 to subtrahend
    ADDLW   0x01
    SUBWF   XTGT_MD,W            ; W = XTGT_MD - (XCUR_MD + borrow)
    MOVWF   DX_MD
    MOVF    XCUR_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   XTGT_HI,W
    MOVWF   DX_HI
    BTFSC   STATUS,C
    GOTO    X_IS_POSITIVE        ; No borrow -> XTGT >= XCUR
    ; Negate DX (24-bit two's complement): ~DX + 1
    COMF    DX_LO,F
    COMF    DX_MD,F
    COMF    DX_HI,F
    MOVLW   0x01
    ADDWF   DX_LO,F              ; C=1 if LO wrapped 0xFF->0x00
    BTFSS   STATUS,C
    GOTO    X_NEGATE_DONE
    INCF    DX_MD,F              ; carry into MD; Z=1 if MD wrapped
    BTFSS   STATUS,Z
    GOTO    X_NEGATE_DONE
    INCF    DX_HI,F
X_NEGATE_DONE
    MOVLW   0x01
    MOVWF   XDIR_F
    GOTO    BRES_CALC_DY
X_IS_POSITIVE
    CLRF    XDIR_F

; --- Compute |DY| and Y direction (24-bit, same pattern) ---
BRES_CALC_DY
    MOVF    YCUR_LO,W
    SUBWF   YTGT_LO,W
    MOVWF   DY_LO
    MOVF    YCUR_MD,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   YTGT_MD,W
    MOVWF   DY_MD
    MOVF    YCUR_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   YTGT_HI,W
    MOVWF   DY_HI
    BTFSC   STATUS,C
    GOTO    Y_IS_POSITIVE
    COMF    DY_LO,F
    COMF    DY_MD,F
    COMF    DY_HI,F
    MOVLW   0x01
    ADDWF   DY_LO,F
    BTFSS   STATUS,C
    GOTO    Y_NEGATE_DONE
    INCF    DY_MD,F
    BTFSS   STATUS,Z
    GOTO    Y_NEGATE_DONE
    INCF    DY_HI,F
Y_NEGATE_DONE
    MOVLW   0x01
    MOVWF   YDIR_F
    GOTO    BRES_SET_DIRS
Y_IS_POSITIVE
    CLRF    YDIR_F

; --- Apply directions to driver DIR pins ---
BRES_SET_DIRS
    BTFSS   XDIR_F,0
    BCF     X_DIR
    BTFSC   XDIR_F,0
    BSF     X_DIR
    ; Y polarity confirmed by hardware test
    BTFSS   YDIR_F,0
    BSF     Y_DIR
    BTFSC   YDIR_F,0
    BCF     Y_DIR

; --- Choose dominant axis: compare |DX| vs |DY| (24-bit) ---
    MOVF    DX_HI,W
    SUBWF   DY_HI,W             ; DY_HI - DX_HI; C=0 if DX_HI > DY_HI
    BTFSS   STATUS,Z
    GOTO    DOM_DECIDED
    MOVF    DX_MD,W
    SUBWF   DY_MD,W
    BTFSS   STATUS,Z
    GOTO    DOM_DECIDED
    MOVF    DX_LO,W
    SUBWF   DY_LO,W
DOM_DECIDED
    BTFSS   STATUS,C            ; C=0 -> DX > DY -> X dominant
    GOTO    SET_X_DOM
SET_Y_DOM
    MOVLW   0x01
    MOVWF   DOM_FLAG
    MOVF    DY_HI,W
    MOVWF   STEPX_HI
    MOVF    DY_MD,W
    MOVWF   STEPX_MD
    MOVF    DY_LO,W
    MOVWF   STEPX_LO
    ; BERR = DY >> 1 (24-bit right-shift through carry)
    BCF     STATUS,C
    RRF     DY_HI,W
    MOVWF   BERR_HI
    RRF     DY_MD,W
    MOVWF   BERR_MD
    RRF     DY_LO,W
    MOVWF   BERR_LO
    GOTO    BRES_LOOP
SET_X_DOM
    CLRF    DOM_FLAG
    MOVF    DX_HI,W
    MOVWF   STEPX_HI
    MOVF    DX_MD,W
    MOVWF   STEPX_MD
    MOVF    DX_LO,W
    MOVWF   STEPX_LO
    ; BERR = DX >> 1
    BCF     STATUS,C
    RRF     DX_HI,W
    MOVWF   BERR_HI
    RRF     DX_MD,W
    MOVWF   BERR_MD
    RRF     DX_LO,W
    MOVWF   BERR_LO

; ===========================================================
;   BRES_LOOP
;   Dominant axis steps every iteration.
;   Minor axis steps when BERR accumulates past dominant delta.
;
;   [v11] 24-bit compare pattern (3-byte borrow propagation):
;     MOVF    DELTA_LO,W
;     SUBWF   BERR_LO,W          ; W = BERR_LO - DELTA_LO
;     MOVF    DELTA_MD,W
;     BTFSS   STATUS,C           ; C=0 -> borrow from lo, add 1 to MD
;     ADDLW   0x01
;     SUBWF   BERR_MD,W
;     MOVF    DELTA_HI,W
;     BTFSS   STATUS,C
;     ADDLW   0x01
;     SUBWF   BERR_HI,W
;     BTFSS   STATUS,C           ; C=1 -> BERR >= DELTA -> step minor axis
;     GOTO    SKIP_MINOR_STEP
; ===========================================================
BRES_LOOP
    ; Check if dominant step counter == 0 (24-bit zero test)
    MOVF    STEPX_HI,W
    IORWF   STEPX_MD,W
    IORWF   STEPX_LO,W
    BTFSC   STATUS,Z
    GOTO    BRES_DONE
    BTFSC   DOM_FLAG,0
    GOTO    STEP_Y_DOM

; --- X dominant: always step X, maybe step Y ---
STEP_X_DOM
    BSF     X_STEP
    ; Accumulate error: BERR += DY (24-bit)
    MOVF    DY_LO,W
    ADDWF   BERR_LO,F
    BTFSC   STATUS,C
    INCF    BERR_MD,F            ; carry from LO (BERR bounded, INCF safe)
    MOVF    DY_MD,W
    ADDWF   BERR_MD,F
    BTFSC   STATUS,C
    INCF    BERR_HI,F
    MOVF    DY_HI,W
    ADDWF   BERR_HI,F
    ; [v11] 24-bit compare: BERR >= DX ?
    MOVF    DX_LO,W
    SUBWF   BERR_LO,W            ; BERR_LO - DX_LO
    MOVF    DX_MD,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_MD,W
    MOVF    DX_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_HI,W
    BTFSS   STATUS,C             ; C=1 -> BERR >= DX, step Y
    GOTO    XD_CLEAR
    BSF     Y_STEP               ; Diagonal step
    ; Subtract DX from BERR (24-bit, borrow-propagating)
    MOVF    DX_LO,W
    SUBWF   BERR_LO,F
    MOVF    DX_MD,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_MD,F
    MOVF    DX_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_HI,F
XD_CLEAR
    NOP
    NOP
    BCF     X_STEP
    BCF     Y_STEP
    CALL    STEP_DELAY
    GOTO    BRES_DEC

; --- Y dominant: always step Y, maybe step X ---
STEP_Y_DOM
    BSF     Y_STEP
    ; Accumulate error: BERR += DX (24-bit)
    MOVF    DX_LO,W
    ADDWF   BERR_LO,F
    BTFSC   STATUS,C
    INCF    BERR_MD,F
    MOVF    DX_MD,W
    ADDWF   BERR_MD,F
    BTFSC   STATUS,C
    INCF    BERR_HI,F
    MOVF    DX_HI,W
    ADDWF   BERR_HI,F
    ; [v11] 24-bit compare: BERR >= DY ?
    MOVF    DY_LO,W
    SUBWF   BERR_LO,W
    MOVF    DY_MD,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_MD,W
    MOVF    DY_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_HI,W
    BTFSS   STATUS,C             ; C=1 -> BERR >= DY, step X
    GOTO    YD_CLEAR
    BSF     X_STEP
    ; Subtract DY from BERR (24-bit)
    MOVF    DY_LO,W
    SUBWF   BERR_LO,F
    MOVF    DY_MD,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_MD,F
    MOVF    DY_HI,W
    BTFSS   STATUS,C
    ADDLW   0x01
    SUBWF   BERR_HI,F
YD_CLEAR
    NOP
    NOP
    BCF     Y_STEP
    BCF     X_STEP
    CALL    STEP_DELAY
; --- Decrement 24-bit dominant step counter ---
BRES_DEC
    MOVLW   0x01
    SUBWF   STEPX_LO,F           ; C=0 if borrow from LO
    BTFSC   STATUS,C
    GOTO    BRES_LOOP
    MOVLW   0x01
    SUBWF   STEPX_MD,F
    BTFSC   STATUS,C
    GOTO    BRES_LOOP
    DECF    STEPX_HI,F
    GOTO    BRES_LOOP
BRES_DONE


    MOVF    XTGT_LO,W
    MOVWF   XCUR_LO
    MOVF    XTGT_MD,W
    MOVWF   XCUR_MD
    MOVF    XTGT_HI,W
    MOVWF   XCUR_HI
    MOVF    YTGT_LO,W
    MOVWF   YCUR_LO
    MOVF    YTGT_MD,W
    MOVWF   YCUR_MD
    MOVF    YTGT_HI,W
    MOVWF   YCUR_HI
    RETURN


STEP_DELAY
    MOVLW   D'1'
    MOVWF   DLY2
SDL_OUTER
    MOVLW   D'16'
    MOVWF   DLY1
SDL_INNER
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    SDL_INNER
    DECFSZ  DLY2,F
    GOTO    SDL_OUTER
    RETURN



HOME_DELAY
    MOVLW   D'2'
    MOVWF   DLY2
HDL_OUT
    MOVLW   D'16'
    MOVWF   DLY1
HDL_IN
    NOP
    NOP
    DECFSZ  DLY1,F
    GOTO    HDL_IN
    DECFSZ  DLY2,F
    GOTO    HDL_OUT
    RETURN



SEND_ACK
    BTFSS   PIR1,TXIF
    GOTO    SEND_ACK
    MOVLW   A'A'
    MOVWF   TXREG
    RETURN


PLOT_DONE
    MOVLW   H'01'
    CALL    COMMAND
    MOVLW   H'86'
    CALL    COMMAND
    MOVLW   A'P'
    CALL    CHAR
    MOVLW   A'L'
    CALL    CHAR
    MOVLW   A'O'
    CALL    CHAR
    MOVLW   A'T'
    CALL    CHAR
    MOVLW   H'C5'
    CALL    COMMAND
    MOVLW   A'D'
    CALL    CHAR
    MOVLW   A'O'
    CALL    CHAR
    MOVLW   A'N'
    CALL    CHAR
    MOVLW   A'E'
    CALL    CHAR
    MOVLW   A'!'
    CALL    CHAR
    GOTO    $




COMMAND
    BCF     PORTE,2
    BCF     PORTE,1
    BCF     PORTE,0
    MOVWF   PORTD
    NOP
    NOP
    NOP
    NOP
    BSF     PORTE,0
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    BCF     PORTE,0
    CALL    DELAY10MS
    RETURN
CHAR
    BSF     PORTE,2
    BCF     PORTE,1
    BCF     PORTE,0
    MOVWF   PORTD
    NOP
    NOP
    NOP
    NOP
    BSF     PORTE,0
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    NOP
    BCF     PORTE,0
    CALL    DELAY10MS
    RETURN
CONFILCD
    CLRF    PORTE
    CLRF    PORTD
    CALL    DELAY20MS
    CALL    DELAY20MS
    CALL    DELAY20MS
    MOVLW   H'38'
    CALL    COMMAND
    MOVLW   H'38'
    CALL    COMMAND
    MOVLW   H'38'
    CALL    COMMAND
    MOVLW   H'38'
    CALL    COMMAND
    MOVLW   H'08'
    CALL    COMMAND
    MOVLW   H'01'
    CALL    COMMAND
    CALL    DELAY20MS
    MOVLW   H'06'
    CALL    COMMAND
    MOVLW   H'0C'
    CALL    COMMAND
    RETURN

DELAY20MS
    MOVLW   D'1'
    MOVWF   REG3
    MOVLW   D'25'
    MOVWF   REG2
    MOVLW   D'255'
    MOVWF   REG1
    DECFSZ  REG1,F
    GOTO    $-1
    DECFSZ  REG2,F
    GOTO    $-5
    DECFSZ  REG3,F
    GOTO    $-9
    RETURN
DELAY10MS
    MOVLW   D'1'
    MOVWF   REG3
    MOVLW   D'13'
    MOVWF   REG2
    MOVLW   D'255'
    MOVWF   REG1
    DECFSZ  REG1,F
    GOTO    $-1
    DECFSZ  REG2,F
    GOTO    $-5
    DECFSZ  REG3,F
    GOTO    $-9
    RETURN
    END
