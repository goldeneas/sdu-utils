// Edit the values below to change what both screens show, then reload the page.
//
// - Leave a key out (or delete it) to keep the built-in default text for that field.
// - Set a text field to "" (or null) to hide that element completely.
// - Everything is plain text: no HTML.
window.APP_CONFIG = {

  // Small pill shown at the bottom of each screen. Edit the wording if you like.
  banner: {
    payment: "UI mock · not a real payment",
    cards: "UI mock · placeholder data"
  },

  // ---------------------------------------------------------------- index.html
  payment: {
    amount: "10",                    // number shown big at the top, as text
    currency: "DKK",                 // currency code, also used in "How you paid"
    amountTaken: null,               // optional; null = same as "<amount> <currency>"
    flag: "DK",                      // DK NO SE FI DE FR IT NL PL AT BE IE | "" = no flag

    merchant: "FynBus",        // name under the amount and in the footer
    footerName: null,                // optional; null = same as merchant
    category: "Bills",               // chip under the merchant ("" hides it)

    when: "1 January 2026 at 09:00",
    where: "Online",
    card: "5092",                    // card shown in "Which card"
    authorisedVia: "Apple Pay",
    authorisedBadge: "PAY",          // small badge next to it ("" hides it)
    note: "",                        // "" = shows the "Add" link, otherwise shows this text
    transactionNo: "4413885726",

    splitInitials: "NP"              // initials bubble in the "Split" box
  },

  // Fixed labels of the payment screen
  paymentTexts: {
    splitTitle: "Split this transaction",
    splitSubtitle: "Request money from others",
    detailsHeading: "Transaction details",
    receiptTitle: "Add receipt",
    receiptHint: "PDF, JPEG or PNG less than 10MB",
    paidHeading: "How you paid",
    amountTakenLabel: "Amount taken"
  },

  // ---------------------------------------------------------------- cards.html
  cards: {
    title: "Cards",                  // big title and the collapsed top-bar title
    leftButton: "Travel hub",        // pill, top left
    rightButton: "Card",             // green pill, top right

    cardName: "Digital card",        // text under the card
    last4: "5092",                   // last digits under the card
    artworkTop: "",                  // big text drawn over the card ("" = none; the picture has its own logo)
    artworkBottom: "",               // text at the bottom of the card ("" = none)
    cardImage: "assets/card-bg.jpg", // optional picture drawn over the card; "" = never try it

    walletNote: "Added to phone wallet",   // "" hides it

    actions: {                       // the three round buttons ("" hides one)
      pin: "Show PIN",
      details: "Card details",
      freeze: "Freeze card"
    },

    manageHeading: "Manage card",
    items: {                         // "Manage card" list, in this order ("" hides one)
      transactions: "View recent card transactions",
      controls: "Card controls",
      unblockPin: "Unblock PIN",
      edit: "Edit card",
      limits: "Your spending limits",
      replace: "Replace card",
      remove: "Delete card"
    },

    tabs: {                          // floating tab bar
      home: "Home",
      cards: "Cards",
      recipients: "Recipients",
      payments: "Payments"
    }
  }
};
